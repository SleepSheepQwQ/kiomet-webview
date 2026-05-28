#!/usr/bin/env python3
import socket, time, json, os, base64

def get_ws():
    import urllib.request
    resp = json.loads(urllib.request.urlopen("http://127.0.0.1:9989/json", timeout=5).read())
    return next(p["webSocketDebuggerUrl"] for p in resp if "kiomet.com" in p.get("url",""))

s = socket.socket(); s.settimeout(15)
s.connect(("127.0.0.1", 9989))
path = get_ws().replace("ws://127.0.0.1:9989", "")
key = base64.b64encode(os.urandom(16)).decode()
s.send(f"GET {path} HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
time.sleep(1); s.recv(4096)

def send(mid, method, params=None):
    p = {"id": mid, "method": method}
    if params: p["params"] = params
    data = json.dumps(p).encode(); mask = os.urandom(4); md = bytearray(len(data))
    for i in range(len(data)): md[i] = data[i] ^ mask[i & 3]
    f = bytearray([0x81]); L = len(data)
    if L < 126: f.append(0x80 | L)
    elif L < 65536: f.append(0x80 | 126); f.extend(L.to_bytes(2, "big"))
    else: f.append(0x80 | 127); f.extend(L.to_bytes(8, "big"))
    f += bytearray(mask) + bytearray(md); s.send(bytes(f))

def recv(timeout=2):
    s.settimeout(timeout); frames = []
    try:
        while True:
            b1 = s.recv(1); oc = b1[0]&0x0f; b2 = s.recv(1)[0]; L = b2&0x7f
            if L==126: L=int.from_bytes(s.recv(2),"big")
            elif L==127: L=int.from_bytes(s.recv(8),"big")
            if oc==0x8: break
            if oc==0x9: s.send(bytes([0x8a,0x00])); continue
            frames.append(json.loads(s.recv(L).decode()))
    except: pass
    return frames

def js(expr):
    send(99, "Runtime.evaluate", {"expression": expr, "returnByValue": True})
    time.sleep(0.5)
    for r in recv():
        if "result" in r and "result" in r["result"]:
            return r["result"]["result"].get("value")

send(1, "Runtime.enable"); time.sleep(0.3); recv()

scripts = js("Array.from(document.scripts).map(function(s){return s.src}).filter(function(s){return s.length>0}).join(', ')")
print("Scripts:", scripts, flush=True)

# Find wasm URL in the client.js loader
wasm = js("""
(function(){
  var src = '';
  Array.from(document.scripts).some(function(s){
    if(s.src.indexOf('client')>0||s.src.indexOf('kiomet_bg')>0){src=s.src;return true;}
    return false;
  });
  if(src) return src;
  // Try to find in inline scripts
  Array.from(document.scripts).some(function(s){
    var m = (s.text||s.innerHTML).match(/['"]([^'"]+\\.wasm)['"]/);
    if(m){src=m[1];return true;}
    return false;
  });
  return src || 'not_found';
})()
""")
print("WASM URL:", wasm, flush=True)

# Check __kbWm entries for current session
count = js("window.__kbWm ? window.__kbWm.length : 0")
print("Wm entries:", count, flush=True)

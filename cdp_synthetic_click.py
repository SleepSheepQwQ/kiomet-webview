
"""Check canvas event listeners and dispatch synthetic events."""
import socket, time, json, os, base64

def get_ws():
    import urllib.request
    resp = json.loads(urllib.request.urlopen("http://127.0.0.1:9989/json", timeout=5).read())
    return next(p["webSocketDebuggerUrl"] for p in resp if "kiomet.com" in p.get("url",""))

s = socket.socket(); s.settimeout(30)
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

def recv_one(timeout=2):
    s.settimeout(timeout)
    try:
        b1 = s.recv(1); oc = b1[0]&0x0f; b2 = s.recv(1)[0]; L = b2&0x7f
        if L==126: L=int.from_bytes(s.recv(2),"big")
        elif L==127: L=int.from_bytes(s.recv(8),"big")
        if oc==0x8: return None
        if oc==0x9: s.send(bytes([0x8a,0x00])); return None
        return json.loads(s.recv(L).decode())
    except: return None

def js(expr):
    send(99, "Runtime.evaluate", {"expression": expr, "returnByValue": True})
    time.sleep(0.5)
    for _ in range(4):
        r = recv_one(1)
        if r and "result" in r and "result" in r["result"]:
            return r["result"]["result"].get("value")

send(1, "Network.enable"); time.sleep(0.5); recv_one(1)
send(2, "Runtime.enable"); time.sleep(0.3); recv_one(1)

print("Canvas listeners:", js("""
(function(){
  var c = document.querySelector('canvas');
  if(!c) return 'no_canvas';
  var info = [];
  var events = ['onmousedown','onmouseup','onclick','ontouchstart','ontouchend','onpointerdown','onpointerup'];
  for(var e of events) { if(c[e]) info.push(e); }
  return JSON.stringify(info);
})()"""), flush=True)


print("Synthetic click:", js("""
(function(){
  try {
    var c = document.querySelector('canvas');
    c.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:311, clientY:86, button:0}));
    c.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, clientX:311, clientY:86, button:0}));
    return 'ok';
  } catch(e) { return String(e); }
})()"""), flush=True)

time.sleep(2)
for j in range(8):
    msg = recv_one(1.5)
    if msg and msg.get("method") == "Network.webSocketFrameSent":
        try:
            data = msg["params"]["request"]["payloadData"]
            raw = base64.b64decode(data) if data else b""
            if raw: print(f"  >>> OUT! hex={raw.hex()}", flush=True)
        except: pass


print("Synthetic touch:", js("""
(function(){
  try {
    var c = document.querySelector('canvas');
    var touch = new Touch({identifier:0, target:c, clientX:311, clientY:86});
    c.dispatchEvent(new TouchEvent('touchstart', {bubbles:true, cancelable:true, changedTouches:[touch], touches:[touch]}));
    c.dispatchEvent(new TouchEvent('touchend', {bubbles:true, cancelable:true, changedTouches:[touch]}));
    return 'touch_ok';
  } catch(e) { return String(e); }
})()"""), flush=True)

time.sleep(2)
for j in range(8):
    msg = recv_one(1.5)
    if msg and msg.get("method") == "Network.webSocketFrameSent":
        try:
            data = msg["params"]["request"]["payloadData"]
            raw = base64.b64decode(data) if data else b""
            if raw: print(f"  >>> OUT! hex={raw.hex()}", flush=True)
        except: pass

print("Done", flush=True)

"""Find tower positions from CDP screenshots."""
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

send(1, "Page.enable"); time.sleep(0.3); recv()




import urllib.request
resp = urllib.request.urlopen("http://127.0.0.1:9989/json").read()
pages = json.loads(resp)
for p in pages:
    if "kiomet.com" in p.get("url",""):
        print(f"Page: {p['title']} url={p['url']}", flush=True)



send(2, "Runtime.evaluate", {"expression": "JSON.stringify(Object.keys(localStorage).map(function(k){return k+':'+localStorage.getItem(k).slice(0,100)}))", "returnByValue": True})
time.sleep(1)
for r in recv():
    if "result" in r and "result" in r["result"]:
        v = r["result"]["result"].get("value")
        if v: print(f"localStorage: {v[:500]}", flush=True)


send(3, "Runtime.evaluate", {"expression": """
(function(){
  var c = document.querySelector('canvas');
  if(!c) return 'no_canvas';
  var r = c.getBoundingClientRect();
  return JSON.stringify({left: r.left, top: r.top, width: r.width, height: r.height, scrollX: window.scrollX, scrollY: window.scrollY});
})()""", "returnByValue": True})
time.sleep(1)
for r in recv():
    if "result" in r and "result" in r["result"]:
        v = r["result"]["result"].get("value")
        if v: print(f"Canvas pos: {v}", flush=True)




send(4, "Runtime.evaluate", {"expression": """
(function(){
  var b = new Uint8Array(window.__kbMem);
  var MAX = Math.min(b.length, 2097152); // 2MB
  var results = [];
  // Scan for WorldChunks in the heap by looking for Box pointers
  // Box<[Option<Tower>; 256]> has size 256*sizeof(Option<Tower>) ~= 13312 bytes
  // Look for pointers to large allocations
  var dv = new DataView(b.buffer);
  var step = 64;
  for(var off = 0; off < MAX - 8; off += step) {
    var ptr = dv.getUint32(off, true);
    // A reasonable allocation pointer is in range [1024, memory_size)
    if(ptr >= 1024 && ptr < MAX - 13312) {
      // Check if ptr points to Option<Tower> array
      // First byte should be tag (0 or 1)
      var tag = b[ptr];
      if(tag <= 1) {
        // Check stride 52 for more tags
        var consecutive = 0;
        for(var i = 0; i < 10; i++) {
          if(b[ptr + i*52] <= 1) consecutive++;
          else break;
        }
        if(consecutive > 8) {
          results.push({globalOff: off, ptr: ptr, consecTags: consecutive});
        }
      }
    }
  }
  return JSON.stringify({found: results.length, ptrs: results.slice(0,20)});
})()""", "returnByValue": True})
time.sleep(2)
for r in recv():
    if "result" in r and "result" in r["result"]:
        v = r["result"]["result"].get("value")
        if v: print(f"World ptrs: {v}", flush=True)
    else:
        print(f"Partial: {json.dumps(r)[:300]}", flush=True)

print("Done", flush=True)
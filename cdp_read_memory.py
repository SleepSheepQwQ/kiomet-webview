
import socket, time, json, os, base64

def get_ws():
    import urllib.request
    resp = json.loads(urllib.request.urlopen("http://127.0.0.1:9989/json", timeout=5).read())
    for p in resp:
        if "kiomet.com" in p.get("url", ""):
            return p["webSocketDebuggerUrl"]

def connect(ws_url):
    s = socket.socket()
    s.settimeout(15)
    s.connect(("127.0.0.1", 9989))
    path = ws_url.replace("ws://127.0.0.1:9989", "")
    key = base64.b64encode(os.urandom(16)).decode()
    s.send(f"GET {path} HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
    time.sleep(1)
    s.recv(4096)
    return s

def send(s, mid, method, params=None):
    p = {"id": mid, "method": method}
    if params: p["params"] = params
    data = json.dumps(p).encode()
    mask = os.urandom(4)
    md = bytearray(len(data))
    for i in range(len(data)):
        md[i] = data[i] ^ mask[i & 3]
    f = bytearray([0x81])
    L = len(data)
    if L < 126: f.append(0x80 | L)
    elif L < 65536:
        f.append(0x80 | 126)
        f.extend(L.to_bytes(2, 'big'))
    else:
        f.append(0x80 | 127)
        f.extend(L.to_bytes(8, 'big'))
    f += bytearray(mask) + bytearray(md)
    s.send(bytes(f))

def recv(s, timeout=2):
    s.settimeout(timeout)
    frames = []
    try:
        while True:
            b1 = s.recv(1)
            if not b1: break
            oc = b1[0] & 0x0f
            b2 = s.recv(1)[0]
            L = b2 & 0x7f
            if L == 126: L = int.from_bytes(s.recv(2), 'big')
            elif L == 127: L = int.from_bytes(s.recv(8), 'big')
            if oc == 0x8: break
            if oc == 0x9:
                s.send(bytes([0x8a, 0x00]))
                continue
            if L > 0:
                frames.append(json.loads(s.recv(L).decode()))
    except: pass
    return frames

def js(s, mid, expr):
    send(s, mid, "Runtime.evaluate", {"expression": expr, "returnByValue": True})
    time.sleep(0.5)
    for r in recv(s, 2):
        if "result" in r and "result" in r["result"]:
            return r["result"]["result"].get("value")

s = connect(get_ws())
send(s, 1, "Runtime.enable")
time.sleep(0.3)
recv(s, 1)


dump = js(s, 2, """
(function(){
  var b = new Uint8Array(window.__kbMem.buffer);
  var off = 807160;
  var hex = [];
  for(var i = 0; i < 100; i++) {
    hex.push(b[off+i].toString(16).padStart(2,'0'));
  }
  return hex.join(' ');
})()""")
print(f"Mem dump 807160-807259: {dump}", flush=True)


print("\n__kbTowers type:", js(s, 3, "Object.prototype.toString.call(window.__kbTowers)"), flush=True)
print("__kbTowers length/keys:", js(s, 4, """
JSON.stringify({
  isArray: Array.isArray(window.__kbTowers),
  length: window.__kbTowers.length,
  keys: Object.keys(window.__kbTowers).slice(0,10),
  first: window.__kbTowers[0] ? JSON.stringify(window.__kbTowers[0]).slice(0,200) : null,
  ownKeys: Object.getOwnPropertyNames(window.__kbTowers).slice(0,10)
})
"""), flush=True)


print("\nSearching for towers with positive units...", flush=True)
towers = js(s, 5, """
(function(){
  var b = new Uint8Array(window.__kbMem.buffer);
  var result = [];
  for(var off = 0; off < b.length - 30; off += 1) {
    if(b[off] !== 1) continue;
    var units = new Float32Array(window.__kbMem.buffer.slice(off+4, off+8))[0];
    if(units < 1 || units > 200000) continue;
    var player = b[off+2] | (b[off+3] << 8);
    if(player > 4) continue;
    var type = b[off+8];
    if(type > 3) continue;
    result.push({off: off, player: player, units: Math.round(units), type: type});
    if(result.length >= 50) break;
  }
  return JSON.stringify({found: result.length, list: result});
})()""")
print(f"Towers with units: {towers}", flush=True)


dump2 = js(s, 6, """
(function(){
  var b = new Uint8Array(window.__kbMem.buffer);
  var off = 804000;
  var hex = [];
  for(var i = 0; i < 80; i++) {
    hex.push(b[off+i].toString(16).padStart(2,'0'));
  }
  return hex.join(' ');
})()""")
print(f"\nMem dump 804000-804079: {dump2}", flush=True)


dump3 = js(s, 7, """
(function(){
  var b = new Uint8Array(window.__kbMem.buffer);
  var off = 0;
  var hex = [];
  for(var i = 0; i < 200; i++) {
    hex.push(b[off+i].toString(16).padStart(2,'0'));
  }
  return hex.join(' ');
})()""")
print(f"Mem dump from start: {dump3}", flush=True)


print("\nLooking for chunk structure (256 Option<Tower>)...", flush=True)
chunk_scan = js(s, 8, """
(function(){
  var b = new Uint8Array(window.__kbMem.buffer);
  var chunks = [];
  for(var off = 0; off < b.length - 256; off += 1) {
    if(b[off] > 1) continue; // first tag must be 0 or 1
    // Check if this repeats every struct_size bytes
    var step = 53;
    var misses = 0;
    for(var j = 0; j < 100 && (off + j*step) < b.length; j++) {
      var tag = b[off + j*step];
      if(tag > 1) misses++;
      if(misses > 10) break;
    }
    if(misses <= 10) {
      chunks.push({off: off, step: step, checked: 100, misses: misses});
    }
    if(chunks.length >= 3) break;
  }
  return JSON.stringify(chunks);
})()""")
print(f"Chunk scan: {chunk_scan}", flush=True)




print("\nFinding tag array by stride...", flush=True)
tags = js(s, 9, """
(function(){
  var b = new Uint8Array(window.__kbMem.buffer);
  for(var stride = 40; stride < 70; stride++) {
    for(var off = 800000; off < 810000; off++) {
      var count = 0;
      for(var j = 0; j < 256 && (off + j*stride) < b.length; j++) {
        var tag = b[off + j*stride];
        if(tag === 0 || tag === 1) count++;
        else break;
      }
      if(count === 256) {
        return JSON.stringify({stride: stride, offset: off});
      }
    }
  }
  return 'not_found';
})()""")
print(f"Tag array: {tags}", flush=True)


mem_type = js(s, 10, "typeof window.__kbExp.memory")
print(f"\n__kbExp.memory type: {mem_type}", flush=True)

if mem_type == "object":
    mem_check = js(s, 11, """
JSON.stringify({
  hasBuffer: typeof window.__kbExp.memory.buffer,
  byteLength: window.__kbExp.memory.buffer.byteLength
})
""")
    print(f"__kbExp.memory: {mem_check}", flush=True)
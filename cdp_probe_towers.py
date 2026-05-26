
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


print("__kbCameraHooked:", js(s, 2, "typeof window.__kbCameraHooked"), flush=True)
print("__kbTowers:", js(s, 3, "typeof window.__kbTowers"), flush=True)
print("__kbTowers val:", js(s, 4, "window.__kbTowers ? window.__kbTowers.toString().slice(0,200) : 'none'"), flush=True)
print("__kbExp names:", js(s, 5, "Object.keys(window.__kbExp).join(', ')"), flush=True)


print("\nLooking for game state functions in exports...", flush=True)
for fn_name in ["main"]:
    res = js(s, 6, f"typeof window.__kbExp.{fn_name}")
    print(f"  __kbExp.{fn_name}: {res}", flush=True)






scan = js(s, 7, """
(function(){
  var b = new Uint8Array(window.__kbMem.buffer);
  var results = [];
  // Chunk size roughly 256 * 55 = 14080 for Some towers
  // But more compact if mostly None
  for(var off = 0; off < b.length - 100; off += 4) {
    // Look for tag=1 (Option::Some) followed by data that looks like a Tower
    if(b[off] !== 1) continue;
    // Found a Some tag - next ~55 bytes should be a Tower
    // player_id at offset+2 (u16 little endian)
    var player = b[off+2] | (b[off+3] << 8);
    if(player > 4) continue;
    // units as f32 at offset+4
    var units = new Float32Array(window.__kbMem.buffer.slice(off+4, off+8))[0];
    if(units <= 0 || units > 200000) continue;
    // tower_type at offset+8
    var type = b[off+8];
    if(type > 3) continue;
    // delay as f32 at offset+12 (4 bytes alignment after u8)
    var delay = new Float32Array(window.__kbMem.buffer.slice(off+12, off+16))[0];
    if(delay < 0 || delay > 1000) continue;
    results.push({off: off, player: player, units: Math.round(units), type: type, delay: Math.round(delay*10)/10});
    if(results.length >= 30) break;
  }
  return JSON.stringify(results);
})()""")
print(f"\nSome towers found: {scan}", flush=True)


scan2 = js(s, 8, """
(function(){
  var b = new Uint8Array(window.__kbMem.buffer);
  var r2 = [];
  for(var off = 0; off < b.length - 64; off += 1) {
    if(b[off] !== 1) continue;
    // tag=1 found. Try to find chunks by looking for patterns of 256 tags
    // Check if next ~256 bytes are Option bytes (0 or 1)
    var tag_count = 0;
    var chunk_start = off;
    for(var j = 0; j < 256 && (off + j * 53) < b.length; j++) {
      var t = b[off + j * 53];
      if(t > 1) break;
      tag_count++;
    }
    if(tag_count >= 200) {
      r2.push({chunk_off: off, filled: tag_count, total_tags: tag_count});
      off += 256 * 53;
      if(r2.length >= 5) break;
    }
  }
  return JSON.stringify(r2);
})()""")
print(f"Chunk scan: {scan2}", flush=True)



dump = js(s, 9, """
(function(){
  var b = new Uint8Array(window.__kbMem.buffer);
  var off = 803900;
  var hex = [];
  for(var i = 0; i < 128; i++) {
    hex.push(b[off+i].toString(16).padStart(2,'0'));
  }
  return hex.join(' ');
})()""")
print(f"\nMem dump at 803900:", dump, flush=True)


dump2 = js(s, 10, """
(function(){
  var b = new Uint8Array(window.__kbMem.buffer);
  var off = 580000;
  var hex = [];
  for(var i = 0; i < 256; i++) {
    hex.push(b[off+i].toString(16).padStart(2,'0'));
  }
  return hex.join(' ');
})()""")
print(f"Mem dump at 580000:", dump2, flush=True)
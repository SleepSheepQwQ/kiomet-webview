
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
            v = r["result"]["result"].get("value")
            if v is not None:
                return v

s = connect(get_ws())
send(s, 1, "Runtime.enable")
time.sleep(0.3)
recv(s, 1)


hook = js(s, 2, """
(function(){
  var c = document.querySelector('canvas');
  if(!c || window.__glHooked) return 'already';
  var gl = c.getContext('webgl');
  if(!gl) return 'no_webgl';
  window.__glHooked = true;
  window.__glBuffers = {};
  window.__glDraws = [];

  var origBufferData = gl.bufferData;
  gl.bufferData = function(target, data, usage) {
    var key = target + '_' + (data.byteLength || data.length || 0);
    if(data && data.byteLength) {
      var copy = new Uint8Array(data);
      window.__glBuffers[key] = {target: target, data: Array.from(copy.slice(0, 1024)), len: copy.length};
    }
    return origBufferData.call(this, target, data, usage);
  };

  var origDrawArrays = gl.drawArrays;
  gl.drawArrays = function(mode, first, count) {
    window.__glDraws.push({mode: mode, first: first, count: count, t: Date.now()});
    return origDrawArrays.call(this, mode, first, count);
  };

  var origDrawElements = gl.drawElements;
  gl.drawElements = function(mode, count, type, offset) {
    window.__glDraws.push({mode: mode, count: count, type: type, offset: offset, t: Date.now()});
    return origDrawElements.call(this, mode, count, type, offset);
  };

  return 'hooked';
})()""")
print(f"GL hook: {hook}", flush=True)

time.sleep(3)


for i in range(5):
    time.sleep(3)
    data = js(s, 10 + i, """
JSON.stringify({
  draws: (window.__glDraws || []).slice(-50).map(function(d){ return {m:d.mode,c:d.count}; }),
  bufs: Object.keys(window.__glBuffers || {}).length,
  bufsDetail: Object.entries(window.__glBuffers || {}).slice(0,10).map(function(e){
    return {key: e[0], bytes: e[1].data.slice(0,32).map(function(b){return b.toString(16).padStart(2,'0')}).join(' '), len: e[1].len};
  })
})
""")
    if data:
        print(f"[{i}] {data}", flush=True)
    recv(s, 1)  

print("\nDone", flush=True)
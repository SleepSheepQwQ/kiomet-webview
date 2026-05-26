
"""CDP screenshot + canvas pixel analysis to detect tower positions."""
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

def recv(s, timeout=3):
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
            if v is not None: return v

ws_url = get_ws()
s = connect(ws_url)
send(s, 1, "Page.enable")
time.sleep(0.3)
recv(s, 1)


pixels = js(s, 2, """
(function(){
  var c = document.querySelector('canvas');
  if(!c) return 'no_canvas';
  var gl = c.getContext('webgl') || c.getContext('webgl2');
  if(!gl) return 'no_gl';
  var w = c.width, h = c.height;
  var buf = new Uint8Array(w * h * 4);
  gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, buf);

  // Find non-background pixels (towers)
  // Common background in kiomet: dark green/brown
  var towers = [];
  var step = 4;

  for(var y = 0; y < h; y += step) {
    for(var x = 0; x < w; x += step) {
      var idx = (y * w + x) * 4;
      var r = buf[idx], g = buf[idx+1], b = buf[idx+2], a = buf[idx+3];
      if(a < 128) continue; // transparent
      // Filter background: dark green (35-80, 60-120, 20-60)
      var isBg = (g > r && g > b && r < 100 && b < 80);
      var isDark = (r < 30 && g < 40 && b < 30);
      if(isBg || isDark) continue;
      // Bright colored pixel - likely a tower
      var brightness = r + g + b;
      if(brightness > 200 && brightness < 720) {
        // Check if this is part of a tower cluster
        var nearby = 0;
        for(var dy = -3; dy <= 3; dy++) {
          for(var dx = -3; dx <= 3; dx++) {
            var ni = ((y+dy) * w + (x+dx)) * 4;
            if(ni >= 0 && ni < buf.length) {
              var nb = buf[ni] + buf[ni+1] + buf[ni+2];
              if(nb > 200) nearby++;
            }
          }
        }
        if(nearby > 10) { // tower cluster
          towers.push({x: x, y: y, r: r, g: g, b: b});
        }
      }
    }
  }

  // Deduplicate by clustering nearby pixels
  var clusters = [];
  for(var t of towers) {
    var found = false;
    for(var cl of clusters) {
      var dx = cl.cx - t.x, dy = cl.cy - t.y;
      if(dx*dx + dy*dy < 400) {
        cl.cx = (cl.cx * cl.n + t.x) / (cl.n + 1);
        cl.cy = (cl.cy * cl.n + t.y) / (cl.n + 1);
        cl.n++;
        found = true;
        break;
      }
    }
    if(!found) clusters.push({cx: t.x, cy: t.y, n: 1, r: t.r, g: t.g, b: t.b});
  }

  return JSON.stringify({
    w: w, h: h,
    pixelCount: towers.length,
    clusters: clusters.filter(c => c.n > 5).map(c => ({
      x: Math.round(c.cx), y: Math.round(c.cy), n: c.n,
      color: [c.r, c.g, c.b]
    }))
  });
})()""")
print(f"Canvas analysis: {pixels}", flush=True)


send(s, 10, "Page.captureScreenshot", {"format": "png"})
time.sleep(1.5)
for f in recv(s, 5):
    if "result" in f and "data" in f.get("result", {}):
        data = f["result"]["data"]
        with open("/tmp/screen.png", "wb") as fh:
            fh.write(base64.b64decode(data))
        print(f"Screenshot saved ({len(base64.b64decode(data))} bytes)", flush=True)
        break

print("\nDone", flush=True)
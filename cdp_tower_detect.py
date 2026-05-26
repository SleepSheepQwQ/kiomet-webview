
"""Fast tower detector via CDP screenshots."""
import socket, time, json, os, base64, sys, struct
from itertools import islice

sys.path.insert(0, '/tmp')
import png

CDP_HOST = "127.0.0.1"
CDP_PORT = 9989

class CDP:
    def __init__(self):
        self.s = socket.socket()
        self.s.settimeout(30)
        import urllib.request
        resp = json.loads(urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json", timeout=5).read())
        ws_url = next(p["webSocketDebuggerUrl"] for p in resp if "kiomet.com" in p.get("url",""))
        self.s.connect((CDP_HOST, CDP_PORT))
        path = ws_url.replace(f"ws://{CDP_HOST}:{CDP_PORT}", "")
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.send(f"GET {path} HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        time.sleep(1); self.s.recv(4096)
        self._send(1, "Runtime.enable"); time.sleep(0.3); self._recv()
        self.mid = 100

    def _send(self, mid, method, params=None):
        p = {"id": mid, "method": method}
        if params: p["params"] = params
        data = json.dumps(p).encode()
        mask = os.urandom(4); md = bytearray(len(data))
        for i in range(len(data)): md[i] = data[i] ^ mask[i & 3]
        f = bytearray([0x81]); L = len(data)
        if L < 126: f.append(0x80 | L)
        elif L < 65536: f.append(0x80 | 126); f.extend(L.to_bytes(2, "big"))
        else: f.append(0x80 | 127); f.extend(L.to_bytes(8, "big"))
        f += bytearray(mask) + bytearray(md); self.s.send(bytes(f))

    def _recv(self, timeout=2):
        self.s.settimeout(timeout); frames = []
        try:
            while True:
                b1 = self.s.recv(1); oc = b1[0]&0x0f; b2 = self.s.recv(1)[0]; L = b2&0x7f
                if L==126: L=int.from_bytes(self.s.recv(2),"big")
                elif L==127: L=int.from_bytes(self.s.recv(8),"big")
                if oc==0x8: break
                if oc==0x9: self.s.send(bytes([0x8a,0x00])); continue
                frames.append(json.loads(self.s.recv(L).decode()))
        except: pass
        return frames

    def screenshot(self):
        self.mid += 1
        self._send(self.mid, "Page.captureScreenshot", {"format": "png"})
        time.sleep(1.5)
        for f in self._recv(5):
            if "result" in f and "data" in f.get("result", {}):
                return base64.b64decode(f["result"]["data"])
        return None

    def click(self, x, y):
        self.mid += 1
        self._send(self.mid, "Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
        time.sleep(0.05)
        self.mid += 1
        self._send(self.mid, "Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})
        time.sleep(0.05); self._recv(0.5)

    def js(self, expr):
        self.mid += 1
        self._send(self.mid, "Runtime.evaluate", {"expression": expr, "returnByValue": True})
        time.sleep(0.5)
        for r in self._recv(2):
            if "result" in r and "result" in r["result"]:
                return r["result"]["result"].get("value")

    def close(self):
        self.s.close()

cdp = CDP()

canvas_str = cdp.js("""
(function(){
  var c = document.querySelector('canvas');
  if(!c) return '{}';
  return JSON.stringify({pw: c.width, ph: c.height, cw: Math.round(c.clientWidth), ch: Math.round(c.clientHeight), rect: c.getBoundingClientRect()});
})()""")
info = json.loads(canvas_str) if canvas_str and canvas_str.startswith("{") else {}
pw, ph = info.get("pw", 1218), info.get("ph", 1950)
rect = info.get("rect", {"left": 0, "top": 0})
print(f"Canvas: {pw}x{ph} CSS={info.get('cw','?')}x{info.get('ch','?')} rect={rect}", flush=True)

png_data = cdp.screenshot()
if not png_data:
    print("No screenshot", flush=True); sys.exit(1)

print(f"PNG: {len(png_data)} bytes", flush=True)

rdr = png.Reader(bytes=png_data)
w, h, rows, meta = rdr.asRGBA()
print(f"Image: {w}x{h}", flush=True)


step = 8
tower_pixels = []
for y, row in enumerate(rows):
    if y % step != 0 or y < 100:  
        continue
    for x in range(0, w * 4, step * 4):
        rv, gv, bv, av = row[x], row[x+1], row[x+2], row[x+3]
        if av < 200: continue
        bright = rv + gv + bv
        if bright < 120 or bright > 730: continue
        is_bg = (gv > rv and gv > bv and rv < 80 and bv < 70) or (rv < 30 and gv < 40 and bv < 30) or (rv > 240 and gv > 240 and bv > 240)
        if is_bg: continue
        is_blue = bv > rv + 15 and bv > gv
        is_red = rv > gv + 15 and rv > bv + 15
        is_colored = is_blue or is_red
        if is_colored:
            tower_pixels.append((x//4, y, rv, gv, bv, 'B' if is_blue else 'R'))

scale_x = w / pw
scale_y = h / ph
print(f"Found {len(tower_pixels)} tower pixels, scale=({scale_x:.2f},{scale_y:.2f})", flush=True)

if not tower_pixels:
    print("No towers found!", flush=True)
    cdp.close()
    sys.exit(0)


clusters = []
for px, py, rv, gv, bv, team in tower_pixels:
    found = False
    for cl in clusters:
        if (cl[0] - px)**2 + (cl[1] - py)**2 < 400:
            cl[0] = (cl[0]*cl[4] + px)//(cl[4]+1)
            cl[1] = (cl[1]*cl[4] + py)//(cl[4]+1)
            cl[4] += 1
            found = True; break
    if not found:
        clusters.append([px, py, team, 0, 1])

sig = [c for c in clusters if c[4] > 2]
sig.sort(key=lambda c: c[4], reverse=True)
print(f"Tower clusters (size>2): {len(sig)}", flush=True)

for c in sig[:15]:
    css_x = int(c[0] / scale_x)
    css_y = int(c[1] / scale_y)
    team_mark = "🔵" if c[2] == 'B' else "🔴"
    print(f"  {team_mark} pixel=({c[0]},{c[1]}) css=({css_x},{css_y}) px={c[4]}", flush=True)


if sig:
    t = sig[0]
    cx = int(rect["left"]) + int(t[0] / scale_x)
    cy = int(rect["top"]) + int(t[1] / scale_y)
    print(f"\nClicking at CSS ({cx}, {cy})...", flush=True)
    cdp.click(cx, cy)
    print("Done", flush=True)

cdp.close()
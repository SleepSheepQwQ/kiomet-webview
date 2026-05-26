
"""Tower detector via CDP screenshots + pure Python PNG decode + click."""
import socket, time, json, os, base64, sys

sys.path.insert(0, '/tmp')
import png

CDP_HOST = "127.0.0.1"
CDP_PORT = 9989

def get_page_ws():
    import urllib.request
    resp = json.loads(urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json", timeout=5).read())
    return next(p["webSocketDebuggerUrl"] for p in resp if "kiomet.com" in p.get("url",""))

class CDP:
    def __init__(self):
        self.s = socket.socket()
        self.s.settimeout(30)
        ws_url = get_page_ws()
        self.s.connect((CDP_HOST, CDP_PORT))
        path = ws_url.replace(f"ws://{CDP_HOST}:{CDP_PORT}", "")
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.send(f"GET {path} HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        time.sleep(1)
        self.s.recv(4096)
        self._send(1, "Page.enable")
        time.sleep(0.3)
        self._recv()
        self._send(2, "Runtime.enable")
        time.sleep(0.3)
        self._recv()
        self.msg_id = 100

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
        self.msg_id += 1
        self._send(self.msg_id, "Page.captureScreenshot", {"format": "png"})
        time.sleep(1.5)
        for f in self._recv(5):
            if "result" in f and "data" in f.get("result", {}):
                return base64.b64decode(f["result"]["data"])
        return None

    def click(self, x, y):
        self.msg_id += 1
        self._send(self.msg_id, "Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
        time.sleep(0.1)
        self.msg_id += 1
        self._send(self.msg_id, "Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})
        time.sleep(0.1)
        self._recv(0.5)

    def js(self, expr):
        self.msg_id += 1
        self._send(self.msg_id, "Runtime.evaluate", {"expression": expr, "returnByValue": True})
        time.sleep(0.5)
        for r in self._recv(2):
            if "result" in r and "result" in r["result"]:
                return r["result"]["result"].get("value")

    def close(self):
        self.s.close()

def find_towers(png_bytes, canvas_pixel_w, canvas_pixel_h):
    rdr = png.Reader(bytes=png_bytes)
    w, h, rows, meta = rdr.asRGBA()
    scale_x = w / canvas_pixel_w
    scale_y = h / canvas_pixel_h

    tower_centers = []
    y = 0
    for row in rows:
        if y % 6 == 0:
            for x in range(0, w * 4, 6 * 4):
                rv, gv, bv, av = row[x], row[x+1], row[x+2], row[x+3]
                if av < 200: continue
                bright = rv + gv + bv
                if bright < 120 or bright > 730: continue
                is_bg = (gv > rv and gv > bv and rv < 80 and bv < 70) or (rv < 30 and gv < 40 and bv < 30) or (rv > 240 and gv > 240 and bv > 240)
                if is_bg: continue
                
                is_blue = bv > rv + 20 and bv > gv and bright > 150
                
                is_red = rv > gv + 20 and rv > bv + 20 and bright > 150
                
                is_purple = rv > 100 and bv > 100 and rv + bv > gv * 1.5
                if is_blue or is_red or is_purple:
                    tower_centers.append((x // 4, y, rv, gv, bv))
        y += 1
        if y > h: break

    
    clusters = []
    for px, py, rv, gv, bv in tower_centers:
        found = False
        for cl in clusters:
            if (cl[0] - px)**2 + (cl[1] - py)**2 < 300:
                cl[0] = (cl[0] * cl[4] + px) // (cl[4] + 1)
                cl[1] = (cl[1] * cl[4] + py) // (cl[4] + 1)
                cl[2].append((rv, gv, bv))
                cl[4] += 1
                found = True; break
        if not found:
            clusters.append([px, py, [(rv, gv, bv)], 0, 1])

    significant = [c for c in clusters if c[4] > 3]
    significant.sort(key=lambda c: c[4], reverse=True)

    
    results = []
    for c in significant[:30]:
        css_x = int(c[0] / scale_x)
        css_y = int(c[1] / scale_y)
        avg_r = int(sum(p[0] for p in c[2]) / len(c[2]))
        avg_g = int(sum(p[1] for p in c[2]) / len(c[2]))
        avg_b = int(sum(p[2] for p in c[2]) / len(c[2]))
        team = "BLUE" if avg_b > avg_r + 20 else "RED" if avg_r > avg_g + 20 else "PURPLE"
        results.append({"pixel": (c[0], c[1]), "css": (css_x, css_y), "color": (avg_r, avg_g, avg_b), "size": c[4], "team": team})

    return results

cdp = CDP()


canvas_str = cdp.js("""
(function(){
  var c = document.querySelector('canvas');
  if(!c) return '{}';
  return JSON.stringify({pw: c.width, ph: c.height, cw: Math.round(c.clientWidth), ch: Math.round(c.clientHeight), rect: c.getBoundingClientRect()});
})()""")
canvas_info = json.loads(canvas_str) if canvas_str and canvas_str.startswith("{") else {}
print(f"Canvas: {canvas_info}", flush=True)

pw = canvas_info.get("pw", 1218)
ph = canvas_info.get("ph", 1950)
rect = canvas_info.get("rect", {"left": 0, "top": 0})


png_data = cdp.screenshot()
if not png_data:
    print("Failed to capture screenshot", flush=True)
    sys.exit(1)

print(f"Screenshot: {len(png_data)} bytes", flush=True)


towers = find_towers(png_data, pw, ph)
print(f"Found {len(towers)} tower clusters:", flush=True)
for t in towers[:20]:
    team_mark = "🟦" if t["team"] == "BLUE" else "🔴" if t["team"] == "RED" else "🟣"
    print(f"  {team_mark} pixel=({t['pixel'][0]},{t['pixel'][1]}) css=({t['css'][0]},{t['css'][1]}) color={t['color']} px={t['size']}", flush=True)


if towers:
    t = towers[0]
    cx = rect["left"] + t["css"][0]
    cy = rect["top"] + t["css"][1]
    print(f"\nClicking first tower at CSS ({cx}, {cy})...", flush=True)
    cdp.click(cx, cy)
    print("Clicked!", flush=True)

cdp.close()
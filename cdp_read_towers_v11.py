
"""Read tower positions from CDP + click on them."""
import socket, time, json, os, base64, sys

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

def js(mid, expr):
    send(mid, "Runtime.evaluate", {"expression": expr, "returnByValue": True})
    time.sleep(0.5)
    for r in recv():
        if "result" in r and "result" in r["result"]:
            return r["result"]["result"].get("value")

send(1, "Runtime.enable"); time.sleep(0.3); recv()

pos = js(2, "JSON.stringify(window.__kbTowerPositions)")
print("Tower positions:", pos, flush=True)

screen = js(3, '(document.body.innerText||"").slice(0,300)')
print("Screen:", screen, flush=True)


if pos and pos != "[]" and pos != "null":
    try:
        towers = json.loads(pos)
        if towers and len(towers) > 0:
            for t in towers[:5]:
                sx, sy = t["s"]
                print(f"Clicking tower at ({sx}, {sy})", flush=True)
                send(10, "Input.dispatchMouseEvent", {"type":"mousePressed","x":sx,"y":sy,"button":"left","clickCount":1})
                time.sleep(0.1)
                send(11, "Input.dispatchMouseEvent", {"type":"mouseReleased","x":sx,"y":sy,"button":"left","clickCount":1})
                time.sleep(1)
    except:
        pass
else:
    print("No towers found", flush=True)

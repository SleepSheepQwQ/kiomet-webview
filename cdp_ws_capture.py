
"""Capture WebSocket frames via CDP Network.enable while game is running."""
import socket, time, json, os, base64, sys

def get_ws():
    import urllib.request
    resp = json.loads(urllib.request.urlopen("http://127.0.0.1:9989/json", timeout=5).read())
    for p in resp:
        if "kiomet.com" in p.get("url", ""):
            return p["webSocketDebuggerUrl"]

s = socket.socket(); s.settimeout(30)
ws_url = get_ws()
s.connect(("127.0.0.1", 9989))
path = ws_url.replace("ws://127.0.0.1:9989", "")
key = base64.b64encode(os.urandom(16)).decode()
s.send(f"GET {path} HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
time.sleep(1); s.recv(4096)

def send(mid, method, params=None):
    p = {"id": mid, "method": method}
    if params: p["params"] = params
    data = json.dumps(p).encode()
    mask = os.urandom(4); md = bytearray(len(data))
    for i in range(len(data)): md[i] = data[i] ^ mask[i & 3]
    f = bytearray([0x81]); L = len(data)
    if L < 126: f.append(0x80 | L)
    elif L < 65536: f.append(0x80 | 126); f.extend(L.to_bytes(2, "big"))
    else: f.append(0x80 | 127); f.extend(L.to_bytes(8, "big"))
    f += bytearray(mask) + bytearray(md); s.send(bytes(f))

def recv_one(timeout=30):
    s.settimeout(timeout)
    try:
        b1 = s.recv(1)
        if not b1: return None
        oc = b1[0] & 0x0f; b2 = s.recv(1)[0]; L = b2 & 0x7f
        if L == 126: L = int.from_bytes(s.recv(2), "big")
        elif L == 127: L = int.from_bytes(s.recv(8), "big")
        if oc == 0x8: return None
        if oc == 0x9: s.send(bytes([0x8a, 0x00])); return None
        data = s.recv(L)
        return json.loads(data.decode())
    except socket.timeout:
        return None
    except: return None


send(1, "Runtime.enable"); time.sleep(0.2)
send(2, "Network.enable"); time.sleep(0.2)
recv_one(1); recv_one(1)  

print("Capturing WS frames via CDP Network...", flush=True)
print("Press Ctrl+C to stop", flush=True)

start = time.time()
frame_count = 0
while time.time() - start < 60:
    msg = recv_one(3)
    if msg is None:
        continue
    method = msg.get("method", "")
    params = msg.get("params", {})

    if method == "Network.webSocketFrameReceived":
        frame = params.get("response", {})
        payload = frame.get("payloadData", "")
        mask = frame.get("mask", False)
        ts = params.get("timestamp", 0)
        print(f"[IN]  len={len(payload)} payload={payload[:200]}", flush=True)
        frame_count += 1

    elif method == "Network.webSocketFrameSent":
        frame = params.get("request", {})
        payload = frame.get("payloadData", "")
        print(f"[OUT] len={len(payload)} payload={payload[:200]}", flush=True)
        frame_count += 1

    elif method == "Network.webSocketCreated":
        print(f"[WS] Created: {params.get('url','')}", flush=True)

    frame_count += 1
    if frame_count % 50 == 0:
        print(f"  ... {frame_count} frames so far", flush=True)

print(f"\nCaptured {frame_count} frames in {time.time()-start:.0f}s", flush=True)
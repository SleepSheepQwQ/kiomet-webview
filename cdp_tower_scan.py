import asyncio, json, http.client, os, sys, time, base64

CDP_PORT = 9989
OUT_DIR = os.path.expanduser("~/kiomet_data")

def get_ws_url():
    conn = http.client.HTTPConnection("127.0.0.1", CDP_PORT, timeout=5)
    conn.request("GET", "/json")
    t = json.loads(conn.getresponse().read())
    conn.close()
    if not t: return None
    url = t[0]["webSocketDebuggerUrl"]
    url = url.replace("ws://localhost", f"ws://127.0.0.1:{CDP_PORT}")
    url = url.replace("ws://host", f"ws://127.0.0.1:{CDP_PORT}")
    return url

async def capture(ws_url):
    import websockets
    async with websockets.connect(ws_url, max_size=2**24) as ws:
        await ws.send(json.dumps({"id":1,"method":"Network.enable"}))
        await ws.recv()
        os.makedirs(OUT_DIR, exist_ok=True)
        out = open(os.path.join(OUT_DIR, f"session_{int(time.time())}.jsonl"), "a")
        print("Capturing commands... Play the game! Ctrl+C to stop", flush=True)
        n = 0
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1)
                    msg = json.loads(raw)
                    if msg.get("method") == "Network.webSocketFrameSent":
                        d = msg["params"]["response"].get("payloadData","")
                        if d not in ("AQMB","AQMC","AQMA","AwA=") and d:
                            raw_bytes = base64.b64decode(d)
                            n += 1
                            entry = json.dumps({"ts":time.time(),"b64":d,"hex":raw_bytes.hex(),"len":len(raw_bytes)})
                            out.write(entry+"\n"); out.flush()
                            print(f"[CMD#{n}] {raw_bytes.hex()}", flush=True)
                except asyncio.TimeoutError:
                    pass
        except KeyboardInterrupt:
            print(f"\n{n} commands captured in {OUT_DIR}", flush=True)
        out.close()

if __name__ == "__main__":
    ws_url = get_ws_url()
    if not ws_url:
        print("CDP bridge not responding")
        sys.exit(1)
    asyncio.run(capture(ws_url))

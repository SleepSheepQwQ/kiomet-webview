#!/usr/bin/env python3
"""Long-running CDP session capture. Saves all WS frames with timestamps."""
import asyncio, json, http.client, os, time

CDP_PORT = 9989
OUT_FILE = os.path.expanduser("~/ws_session.jsonl")

async def main():
    conn = http.client.HTTPConnection("127.0.0.1", CDP_PORT, timeout=5)
    conn.request("GET", "/json")
    t = json.loads(conn.getresponse().read())[0]
    conn.close()
    ws_url = t["webSocketDebuggerUrl"].replace("ws://localhost",f"ws://127.0.0.1:{CDP_PORT}")
    ws_url = ws_url.replace("ws://host",f"ws://127.0.0.1:{CDP_PORT}")
    
    import websockets
    async with websockets.connect(ws_url, max_size=2**24) as ws:
        await ws.send(json.dumps({"id":1,"method":"Network.enable"}))
        await ws.send(json.dumps({"id":2,"method":"Runtime.enable"}))
        await ws.recv(); await ws.recv()  # drain responses

        out = open(OUT_FILE, "a")
        cnt = {"in":0,"out":0}
        print(f"Capturing to {OUT_FILE}... Press Ctrl+C to stop", flush=True)
        
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=60)
                msg = json.loads(raw)
                m = msg.get("method","")
                
                if m == "Network.webSocketFrameSent":
                    cnt["out"] += 1
                    d = msg["params"]["response"]
                    entry = {"t":"out","n":cnt["out"],"ts":time.time(),"sz":d.get("payloadSize","?"),"hex":d.get("payloadData","")}
                    out.write(json.dumps(entry)+"\n"); out.flush()
                    if cnt["out"] % 10 == 0:
                        print(f"[OUT #{cnt['out']}] {d.get('payloadData','')[:40]}", flush=True)
                        
                elif m == "Network.webSocketFrameReceived":
                    cnt["in"] += 1
                    d = msg["params"]["response"]
                    entry = {"t":"in","n":cnt["in"],"ts":time.time(),"sz":d.get("payloadSize","?"),"hex":d.get("payloadData","")}
                    out.write(json.dumps(entry)+"\n"); out.flush()
                    
        except asyncio.TimeoutError:
            print(f"\nIdle timeout. Captured: {cnt}", flush=True)
        except KeyboardInterrupt:
            print(f"\nStopped. Captured: {cnt}", flush=True)
        
        out.close()

if __name__ == "__main__":
    asyncio.run(main())

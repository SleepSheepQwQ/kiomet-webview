#!/usr/bin/env python3
"""Read tower positions captured by injected hooks."""
import asyncio, json, http.client, sys
CDP_PORT = 9989

async def main():
    conn = http.client.HTTPConnection("127.0.0.1", CDP_PORT, timeout=5)
    conn.request("GET", "/json")
    t = json.loads(conn.getresponse().read())
    conn.close()
    if not t: print("No CDP target"); return
    ws_url = t[0]["webSocketDebuggerUrl"]
    ws_url = ws_url.replace("ws://localhost", f"ws://127.0.0.1:{CDP_PORT}")

    import websockets
    async with websockets.connect(ws_url, max_size=2**24) as ws:
        await ws.send(json.dumps({"id":1,"method":"Runtime.enable"}))
        await ws.recv()

        expr = "JSON.stringify({t:window.__kbTowers||[],ls:window.__kbLastSend,m:!!window.__kbMem,s:window.__kbLastSend?Array.from(window.__kbLastSend).map(function(x){return x.toString(16).padStart(2,'0')}).join(''):null})"
        await ws.send(json.dumps({"id":2,"method":"Runtime.evaluate","params":{"expression":expr}}))

        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(raw)
            if msg.get("id") == 2:
                d = json.loads(msg.get("result",{}).get("result",{}).get("value","{}"))
                twrs = d.get("t", [])
                print(f"Towers: {len(twrs)}", flush=True)
                for i,t in enumerate(twrs):
                    print(f"  #{i}: ({t[0]:.1f}, {t[1]:.1f}, {t[2]:.1f})", flush=True)
                if d.get("s"): print(f"Last send hex: {d['s']}", flush=True)
                print(f"WASM mem: {'YES' if d.get('m') else 'NO'}", flush=True)
                if not d.get('m'): print("→ Reload game page to activate hooks", flush=True)
                break

asyncio.run(main())

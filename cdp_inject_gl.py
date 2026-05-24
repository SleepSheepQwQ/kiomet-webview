#!/usr/bin/env python3
"""Inject WebGL hook + reload + capture tower vertex data."""

import asyncio, json, sys, http.client, os
CDP_PORT = 9989

GL_HOOK_SCRIPT = """
(function(){
if(window.__kbT)return;window.__kbT=true;
var p=WebGLRenderingContext.prototype;
var obd=p.bufferData;
p.bufferData=function(t,d,u){
    if(d&&d.length>0&&(d instanceof Float32Array||d instanceof Uint16Array)){
        var vals=Array.from(d.slice(0,Math.min(8,d.length))).map(function(x){return typeof x==='number'?x.toFixed(4):x});
        console.log('KB_TOWER',JSON.stringify({op:'buf',t:t,dt:d.constructor.name,len:d.length,vals:vals,us:u}));
    }
    return obd.apply(this,arguments);
};
var ode=p.drawElements;
p.drawElements=function(m,c,t,o){
    console.log('KB_TOWER',JSON.stringify({op:'draw',cnt:c}));
    return ode.apply(this,arguments);
};
var oum=p.uniformMatrix4fv;
p.uniformMatrix4fv=function(l,t,v){
    if(v&&v.length>=16)console.log('KB_TOWER',JSON.stringify({op:'mat',v:Array.from(v).map(function(x){return x.toFixed(4)})}));
    return oum.apply(this,arguments);
};
console.log('KB_TOWER_READY');
})();
"""

async def cdp_call(ws, msg):
    await ws.send(json.dumps(msg))
    while True:
        resp = json.loads(await ws.recv())
        if "id" in resp and resp["id"] == msg["id"]:
            return resp

async def main():
    conn = http.client.HTTPConnection("127.0.0.1", CDP_PORT, timeout=5)
    conn.request("GET", "/json")
    targets = json.loads(conn.getresponse().read())
    conn.close()
    if not targets: print("No targets"); sys.exit(1)

    ws_url = targets[0]["webSocketDebuggerUrl"]
    ws_url = ws_url.replace("ws://localhost", f"ws://127.0.0.1:{CDP_PORT}")
    ws_url = ws_url.replace("ws://host", f"ws://127.0.0.1:{CDP_PORT}")
    print(f"Target: {targets[0].get('url','?')}")

    import websockets
    async with websockets.connect(ws_url, max_size=2**24) as ws:
        r = await cdp_call(ws, {"id":1, "method":"Page.addScriptToEvaluateOnNewDocument", "params":{"source":GL_HOOK_SCRIPT}})
        print(f"Preload hook: {'ok' if 'result' in r else 'ERR'}")

        r = await cdp_call(ws, {"id":2, "method":"Network.enable"})
        print(f"Network: {'ok' if 'result' in r else 'ERR'}")

        r = await cdp_call(ws, {"id":3, "method":"Runtime.enable"})
        print(f"Runtime: {'ok' if 'result' in r else 'ERR'}")

        r = await cdp_call(ws, {"id":4, "method":"Runtime.evaluate", "params":{"expression":
            "var p=WebGLRenderingContext.prototype;var bd=p.bufferData;p.bufferData=function(t,d,u){if(d&&d.length>0&&(d instanceof Float32Array||d instanceof Uint16Array)){var vals=Array.from(d.slice(0,Math.min(8,d.length))).map(function(x){return typeof x==='number'?x.toFixed(4):x});console.log('KB_TOWER',JSON.stringify({op:'buf',t:t,dt:d.constructor.name,len:d.length,vals:vals}))}return bd.apply(this,arguments)};var de=p.drawElements;p.drawElements=function(m,c,t,o){console.log('KB_TOWER',JSON.stringify({op:'draw',cnt:c}));return de.apply(this,arguments)};console.log('KB_LIVE_OK')"
        }})
        v = r.get("result",{}).get("result",{}).get("value","?")
        print(f"Live hook: {v}")

        # Reload the page to trigger preload hook
        print("\nReloading page to trigger preload hook...")
        await ws.send(json.dumps({"id":5, "method":"Page.reload", "params":{"ignoreCache":True}}))

        cnt = {"buf":0, "draw":0, "mat":0, "ws_in":0, "ws_out":0}
        print("Capturing...\n")
        out_fd = open(os.path.expanduser("~/gl_tower_data.jsonl"), "a")

        while cnt["draw"] < 500 and cnt["buf"] < 50:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=6)
                msg = json.loads(raw)
                method = msg.get("method","")
                p = msg.get("params",{})

                if method == "Runtime.consoleAPICalled":
                    args = p.get("args",[])
                    if args:
                        txt = args[0].get("value","")
                        if txt == "KB_TOWER_READY":
                            print(">>> PRELOAD HOOK FIRED <<<")
                        elif txt == "KB_TOWER" and len(args) > 1:
                            d = args[1].get("value","{}")
                            entry = json.loads(d)
                            op = entry.get("op","")
                            if op == "buf":
                                cnt["buf"] += 1
                                print(f"[BUF #{cnt['buf']}] {d[:200]}")
                            elif op == "draw":
                                cnt["draw"] += 1
                            elif op == "mat":
                                cnt["mat"] += 1
                                if cnt["mat"] <= 2:
                                    print(f"[MAT #{cnt['mat']}] {d[:200]}")
                            out_fd.write(json.dumps({"t":"gl",**entry})+"\n")
                            out_fd.flush()

                elif method == "Network.webSocketFrameReceived":
                    cnt["ws_in"] += 1
                elif method == "Network.webSocketFrameSent":
                    cnt["ws_out"] += 1

            except asyncio.TimeoutError:
                print(f"  progress - BUF:{cnt['buf']} DRAW:{cnt['draw']} MAT:{cnt['mat']} WS_IN:{cnt['ws_in']}")
                break

        out_fd.close()
        print(f"\nFinal: {cnt}")
        print(f"Data saved to ~/gl_tower_data.jsonl")

if __name__ == "__main__":
    asyncio.run(main())
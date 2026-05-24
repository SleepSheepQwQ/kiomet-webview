#!/usr/bin/env python3
import asyncio, json, http.client, os, time
CDP_PORT = 9989

GL_HOOK = """
(function(){
if(window.__kbTw)return;window.__kbTw=true;
var p=WebGLRenderingContext.prototype;
var _bd=p.bufferData;
p.bufferData=function(t,d,u){
    if(d&&d.length>0){
        try{
            var vals=Array.from(d.slice(0,Math.min(12,d.length))).map(function(x){return typeof x==='number'?x.toFixed(4):x});
            console.log('KB_TWR',JSON.stringify({op:'buf',t:t,dt:d.constructor.name,len:d.length,vals:vals}));
        }catch(e){}
    }
    return _bd.apply(this,arguments);
};
var _de=p.drawElements;
p.drawElements=function(m,c){console.log('KB_TWR',JSON.stringify({op:'draw',cnt:c}));return _de.apply(this,arguments);};
var _uv=p.uniformMatrix4fv;
p.uniformMatrix4fv=function(l,t,v){if(v&&v.length>=16)console.log('KB_TWR',JSON.stringify({op:'mat',vals:Array.from(v.slice(0,16)).map(function(x){return x.toFixed(4)})}));return _uv.apply(this,arguments);};
console.log('KB_READY');
})();
"""

async def get_target():
    conn = http.client.HTTPConnection("127.0.0.1", CDP_PORT, timeout=5)
    conn.request("GET", "/json")
    targets = json.loads(conn.getresponse().read())
    conn.close()
    return targets[0] if targets else None

async def cdp_call(ws, msg):
    await ws.send(json.dumps(msg))
    while True:
        resp = json.loads(await ws.recv())
        if resp.get("id") == msg["id"]:
            return resp

async def main():
    t = await get_target()
    if not t: print("No target"); return
    ws_url = t["webSocketDebuggerUrl"].replace("ws://localhost",f"ws://127.0.0.1:{CDP_PORT}").replace("ws://host",f"ws://127.0.0.1:{CDP_PORT}")
    print(f"Target: {t.get('url','?')}", flush=True)
    import websockets

    async with websockets.connect(ws_url, max_size=2**24) as ws:
        r = await cdp_call(ws, {"id":1,"method":"Page.addScriptToEvaluateOnNewDocument","params":{"source":GL_HOOK}})
        print(f"Hook: {'ok' if 'result' in r else 'ERR'}", flush=True)

        print("Reloading...", flush=True)
        await ws.send(json.dumps({"id":2,"method":"Runtime.evaluate","params":{"expression":"location.reload()"}}))

    # Wait for new page
    for i in range(15):
        await asyncio.sleep(1)
        t2 = await get_target()
        if t2 and t2.get("webSocketDebuggerUrl","") != t.get("webSocketDebuggerUrl",""):
            break
    else:
        t2 = t

    ws_url2 = t2["webSocketDebuggerUrl"].replace("ws://localhost",f"ws://127.0.0.1:{CDP_PORT}").replace("ws://host",f"ws://127.0.0.1:{CDP_PORT}")
    print(f"Reconnected: {t2.get('url','?')}", flush=True)

    async with websockets.connect(ws_url2, max_size=2**24) as ws:
        await cdp_call(ws, {"id":1,"method":"Runtime.enable"})
        await cdp_call(ws, {"id":2,"method":"Network.enable"})

        out = open(os.path.expanduser("~/tower_data.jsonl"), "a")
        cnt = {"buf":0,"draw":0,"mat":0}
        dl = time.time() + 25

        while time.time() < dl and cnt["buf"] < 50:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=3)
                msg = json.loads(raw)
                if msg.get("method") == "Runtime.consoleAPICalled":
                    a = msg["params"].get("args",[])
                    if a:
                        t = a[0].get("value","")
                        if t == "KB_READY": print(">>> HOOK FIRED <<<", flush=True)
                        elif t == "KB_TWR" and len(a) > 1:
                            d = a[1].get("value","{}")
                            e = json.loads(d)
                            out.write(json.dumps(e)+"\n"); out.flush()
                            if e["op"] == "buf":
                                cnt["buf"] += 1
                                print(f"[BUF#{cnt['buf']}] {d[:250]}", flush=True)
                            elif e["op"] == "draw": cnt["draw"] += 1
                            elif e["op"] == "mat":
                                cnt["mat"] += 1
                                if cnt["mat"] <= 2: print(f"[MAT#{cnt['mat']}] {d[:200]}", flush=True)
            except asyncio.TimeoutError:
                pass

        out.close()
        print(f"\nBUF:{cnt['buf']} DRAW:{cnt['draw']} MAT:{cnt['mat']}", flush=True)

asyncio.run(main())

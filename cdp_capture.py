#!/usr/bin/env python3
"""CDP capture tool kiomet WebView (:9989)."""
import asyncio, json, sys, http.client, os
CDP_PORT = 9989
OUT_FILE = os.path.expanduser("~/cdp_capture.jsonl")

INJECT_SCRIPT = """
(function(){
if(window.__kbCdpInjected)return;
window.__kbCdpInjected=true;
const targets = /__wbg_send_|__wbg_client(X|Y)_|__wbg_bufferData_|__wbg_addEventListener_|__wbg_close_|__wbg_button_/;
const wrap = (mod,fnName,fn)=>{
    const orig = fn;
    mod[fnName]=function(){
        try{
            const a=[];
            for(let i=0;i<arguments.length;i++){
                const v=arguments[i];
                if(v===null||v===undefined)a.push(''+v);
                else if(typeof v==='number'||typeof v==='boolean')a.push(v);
                else if(typeof v==='string')a.push(v.length>80?v.slice(0,80)+'...':v);
                else if(v instanceof ArrayBuffer)a.push('AB('+v.byteLength+')');
                else if(ArrayBuffer.isView(v))a.push(v.constructor.name+'('+v.length+')');
                else a.push(typeof v);
            }
            console.log('KB_WASM',JSON.stringify({f:fnName,a:a}));
        }catch(e){}
        return orig.apply(this,arguments);
    };
};
const hookImports = (imports)=>{
    if(!imports||typeof imports!=='object')return;
    for(const mn of Object.getOwnPropertyNames(imports)){
        const m=imports[mn];
        if(!m||typeof m!=='object')continue;
        for(const fn of Object.getOwnPropertyNames(m)){
            if(typeof m[fn]==='function'&&targets.test(fn))wrap(m,fn,m[fn]);
        }
    }
};
const oi=WebAssembly.instantiate;
WebAssembly.instantiate=async function(b,i){hookImports(i);return oi.call(this,b,i);};
const ois=WebAssembly.instantiateStreaming;
if(ois){WebAssembly.instantiateStreaming=async function(s,i){hookImports(i);return ois.call(this,s,i);};}
console.log('KB_HOOK_READY');
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
    if not targets:
        print("No targets found")
        sys.exit(1)
    ws_url = targets[0]["webSocketDebuggerUrl"]
    ws_url = ws_url.replace("ws://localhost", f"ws://127.0.0.1:{CDP_PORT}")
    ws_url = ws_url.replace("ws://host", f"ws://127.0.0.1:{CDP_PORT}")
    print(f"Target: {targets[0].get('url','?')}")

    out_fd = open(OUT_FILE, "a")
    import websockets

    async with websockets.connect(ws_url, max_size=2**24) as ws:
        r = await cdp_call(ws, {"id":1, "method":"Page.addScriptToEvaluateOnNewDocument", "params":{"source":INJECT_SCRIPT}})
        print(f"  Hook: {'ok' if 'result' in r else 'ERR'}")

        r = await cdp_call(ws, {"id":2, "method":"Network.enable"})
        print(f"  Network: {'ok' if 'result' in r else 'ERR'}")

        r = await cdp_call(ws, {"id":3, "method":"Runtime.enable"})
        print(f"  Runtime: {'ok' if 'result' in r else 'ERR'}")

        r = await cdp_call(ws, {"id":4, "method":"Runtime.evaluate", "params":{"expression":
            "(function(){try{const o=WebSocket.prototype.send;WebSocket.prototype.send=function(d){try{console.log('KB_WS',typeof d==='string'?d.slice(0,100):'binary('+(d.byteLength||d.length)+')')}catch(e){}return o.call(this,d);};return'ok'}catch(e){return e.message}})()"
        }})
        v = r.get("result",{}).get("result",{}).get("value","?")
        print(f"  Live hook: {v}")

        cnt = {"in":0, "out":0, "wasm":0}
        print("\nListening... (Ctrl+C to stop)\n")

        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            method = msg.get("method","")
            p = msg.get("params",{})

            if method == "Network.webSocketFrameSent":
                d = p.get("response",{})
                cnt["out"] += 1
                e = {"t":"out","n":cnt["out"],"sz":d.get("payloadSize","?"),"data":d.get("payloadData","")}
                print(f"[OUT #{e['n']}] sz={e['sz']}  {e['data'][:120]}")
                out_fd.write(json.dumps(e)+"\n"); out_fd.flush()

            elif method == "Network.webSocketFrameReceived":
                d = p.get("response",{})
                cnt["in"] += 1
                e = {"t":"in","n":cnt["in"],"sz":d.get("payloadSize","?"),"data":d.get("payloadData","")}
                print(f"[IN  #{e['n']}] sz={e['sz']}  {e['data'][:120]}")
                out_fd.write(json.dumps(e)+"\n"); out_fd.flush()

            elif method == "Runtime.consoleAPICalled":
                a = p.get("args",[])
                if not a: continue
                txt = a[0].get("value","")
                if txt == "KB_WASM" and len(a) > 1:
                    cnt["wasm"] += 1
                    d = a[1].get("value","{}")
                    e = {"t":"wasm","n":cnt["wasm"],"d":json.loads(d) if isinstance(d,str) else d}
                    print(f"[WASM #{e['n']}] {e['d']}")
                    out_fd.write(json.dumps(e)+"\n"); out_fd.flush()
                elif txt == "KB_HOOK_READY":
                    print("[WASM] Hook ready (next page load)")
                elif txt == "KB_WS" and len(a) > 1:
                    e = {"t":"js_send","d":a[1].get("value","")}
                    print(f"[JS_SEND] {e['d']}")

            elif method == "Network.webSocketCreated":
                print(f"[WS] {p.get('url','?')}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nDone")

#!/usr/bin/env python3
"""Inject WASM hook + navigate + capture via CDP."""

import socket, time, json, os, base64

PATH = "/devtools/page/089584DFEF5EC3351A6BE906F3909609"

INJECT = "(function(){if(window.__kbIns)return;window.__kbIns=true;console.log('KB_HOOK_READY');var wr=function(m,f,o){m[f]=function(){try{var a=[];for(var i=0;i<arguments.length;i++){var v=arguments[i];if(v===null||v===undefined)a.push(''+v);else if(typeof v==='number'||typeof v==='boolean')a.push(v);else if(typeof v==='string')a.push(v.length>60?v.slice(0,60)+'...':v);else if(v instanceof ArrayBuffer)a.push('AB('+v.byteLength+')');else if(ArrayBuffer.isView(v))a.push(v.constructor.name+'('+v.length+')');else a.push(typeof v);}console.log('KB_WASM',JSON.stringify({f:f,a:a}));}catch(e){}return o.apply(this,arguments);};};var oi=WebAssembly.instantiate;WebAssembly.instantiate=async function(b,i){if(i&&typeof i==='object'){for(var mn of Object.getOwnPropertyNames(i)){var m=i[mn];if(m&&typeof m==='object'){for(var fn of Object.getOwnPropertyNames(m)){if(typeof m[fn]==='function'&&/__wbg_send_|__wbg_client(X|Y)_|__wbg_bufferData_/.test(fn))wr(m,fn,m[fn]);}}}}return oi.call(this,b,i);};var ois=WebAssembly.instantiateStreaming;if(ois){WebAssembly.instantiateStreaming=async function(s,i){if(i&&typeof i==='object'){for(var mn of Object.getOwnPropertyNames(i)){var m=i[mn];if(m&&typeof m==='object'){for(var fn of Object.getOwnPropertyNames(m)){if(typeof m[fn]==='function'&&/__wbg_send_|__wbg_client(X|Y)_|__wbg_bufferData_/.test(fn))wr(m,fn,m[fn]);}}}}return ois.call(this,s,i);};}})()"

def connect():
    s = socket.socket()
    s.settimeout(10)
    s.connect(("127.0.0.1", 9989))
    key = base64.b64encode(os.urandom(16)).decode()
    s.send(f"GET {PATH} HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
    time.sleep(1)
    resp = s.recv(4096)
    assert b"101" in resp
    return s

def build_frame(payload):
    data = json.dumps(payload).encode()
    mask = os.urandom(4)
    mdata = bytearray(len(data))
    for i in range(len(data)):
        mdata[i] = data[i] ^ mask[i & 3]
    frame = bytearray()
    frame.append(0x81)
    L = len(data)
    if L < 126:
        frame.append(0x80 | L)
    elif L < 65536:
        frame.append(0x80 | 126)
        frame.extend(L.to_bytes(2, 'big'))
    else:
        frame.append(0x80 | 127)
        frame.extend(L.to_bytes(8, 'big'))
    frame += bytearray(mask) + bytearray(mdata)
    return bytes(frame)

s = connect()
print("Connected", flush=True)

# 1. Inject hook
s.send(build_frame({"id":1,"method":"Page.addScriptToEvaluateOnNewDocument","params":{"source":INJECT}}))
time.sleep(1)
resp = s.recv(65536)
print(f"Hook: id={json.loads(resp[2:]).get('result',{}).get('identifier','?')}", flush=True)

# 2. Network + Runtime
s.send(build_frame({"id":2,"method":"Network.enable"}))
time.sleep(0.5)
resp = s.recv(65536)
print("Network: ok", flush=True)

s.send(build_frame({"id":3,"method":"Runtime.enable"}))
time.sleep(0.5)
resp = s.recv(65536)
print("Runtime: ok", flush=True)

# 3. Navigate
print("\nLoading game...", flush=True)
s.send(build_frame({"id":4,"method":"Page.navigate","params":{"url":"https://kiomet.com"}}))
s.settimeout(0.5)

buf = b""
deadline = time.time() + 20
cnt = {"in":0, "out":0, "wasm":0}

while time.time() < deadline:
    try:
        chunk = s.recv(65536)
        if chunk: buf += chunk
    except: pass

    while len(buf) >= 2:
        plen = buf[1] & 0x7F
        hdr = 2
        if plen == 126:
            plen = int.from_bytes(buf[2:4],'big'); hdr = 4
        elif plen == 127:
            plen = int.from_bytes(buf[2:10],'big'); hdr = 10
        if len(buf) < hdr + plen: break
        try:
            msg = json.loads(buf[hdr:hdr+plen])
            method = msg.get("method","")
            if msg.get("id") == 4 and "result" in msg:
                print(f"  navigating...", flush=True)
            elif method == "Page.frameNavigated":
                u = msg["params"]["frame"]["url"]
                print(f"[PAGE] {u}", flush=True)
            elif method == "Runtime.consoleAPICalled":
                args = msg["params"].get("args",[])
                if args:
                    txt = args[0].get("value","")
                    if txt == "KB_HOOK_READY":
                        print(">>> HOOK ACTIVE <<<", flush=True)
                    elif txt == "KB_WASM" and len(args) > 1:
                        cnt["wasm"] += 1
                        d = args[1].get("value","")
                        print(f"[WASM #{cnt['wasm']}] {d[:200]}", flush=True)
            elif method == "Network.webSocketFrameSent":
                cnt["out"] += 1
                d = msg["params"]["response"].get("payloadData","")
                print(f"[OUT #{cnt['out']}] {d[:80]}", flush=True)
            elif method == "Network.webSocketFrameReceived":
                cnt["in"] += 1
                if cnt["in"] <= 3:
                    d = msg["params"]["response"].get("payloadData","")
                    print(f"[IN #{cnt['in']}] {d[:80]}", flush=True)
            elif method == "Network.webSocketCreated":
                print(f"[WS] created", flush=True)
        except: pass
        buf = buf[hdr+plen:]

print(f"\n{cnt}", flush=True)
s.close()
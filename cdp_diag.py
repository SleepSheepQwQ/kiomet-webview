#!/usr/bin/env python3
import socket, time, json, os, base64, sys

def get_page_ws():
    import urllib.request
    resp = json.loads(urllib.request.urlopen("http://127.0.0.1:9989/json", timeout=5).read())
    for p in resp:
        if "kiomet.com" in p.get("url", ""):
            return p["webSocketDebuggerUrl"], p["id"]
    return resp[0]["webSocketDebuggerUrl"], resp[0]["id"]

def connect(ws_url):
    s = socket.socket()
    s.settimeout(15)
    s.connect(("127.0.0.1", 9989))
    path = ws_url.replace("ws://127.0.0.1:9989", "")
    key = base64.b64encode(os.urandom(16)).decode()
    s.send(f"GET {path} HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
    time.sleep(1)
    resp = s.recv(4096)
    assert b"101" in resp
    return s

def send_cmd(s, msg_id, method, params=None):
    payload = {"id": msg_id, "method": method}
    if params: payload["params"] = params
    data = json.dumps(payload).encode()
    mask = os.urandom(4)
    mdata = bytearray(len(data))
    for i in range(len(data)):
        mdata[i] = data[i] ^ mask[i & 3]
    frame = bytearray([0x81])
    L = len(data)
    if L < 126: frame.append(0x80 | L)
    elif L < 65536:
        frame.append(0x80 | 126)
        frame.extend(L.to_bytes(2, 'big'))
    else:
        frame.append(0x80 | 127)
        frame.extend(L.to_bytes(8, 'big'))
    frame += bytearray(mask) + bytearray(mdata)
    s.send(bytes(frame))

def recv_all(s, timeout=2):
    s.settimeout(timeout)
    frames = []
    try:
        while True:
            b1 = s.recv(1)
            if not b1: break
            opcode = b1[0] & 0x0f
            b2 = s.recv(1)[0]
            length = b2 & 0x7f
            if length == 126: length = int.from_bytes(s.recv(2), 'big')
            elif length == 127: length = int.from_bytes(s.recv(8), 'big')
            if opcode == 0x8: break
            if opcode == 0x9:
                s.send(bytes([0x8a, 0x00]))
                continue
            frames.append(json.loads(s.recv(length).decode()))
    except socket.timeout: pass
    return frames

def eval_js(s, msg_id, js):
    send_cmd(s, msg_id, "Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": False})
    time.sleep(0.5)
    for r in recv_all(s, 2):
        if "result" in r and "result" in r["result"]:
            return r["result"]["result"].get("value")

ws_url, page_id = get_page_ws()
print(f"Page: {page_id[:16]}...", flush=True)
s = connect(ws_url)
print("Connected", flush=True)

send_cmd(s, 1, "Runtime.enable")
time.sleep(0.5)
recv_all(s, 1)

url = eval_js(s, 2, "window.location.href")
print(f"URL: {url}", flush=True)

wasm_check = eval_js(s, 3, "typeof WebAssembly === 'undefined' ? 'no_wasm' : 'wasm_ok'")
print(f"WASM: {wasm_check}", flush=True)

hook_check = eval_js(s, 4, "JSON.stringify({installed: !!window.__kbInstalled, hook: !!window.__kbHook, mem: !!window.__kbMem, exp: !!window.__kbExports})")
print(f"Hooks: {hook_check}", flush=True)

canvas_check = eval_js(s, 5, """
(function(){
  var c = document.querySelector('canvas');
  if(!c) return 'no_canvas';
  var ctx = c.getContext('webgl') || c.getContext('webgl2');
  return JSON.stringify({w: c.width, h: c.height, gl: !!ctx, visible: c.offsetParent !== null});
})()""")
print(f"Canvas: {canvas_check}", flush=True)

buttons = eval_js(s, 6, """
JSON.stringify(Array.from(document.querySelectorAll('button')).map(b => ({text: b.textContent.trim(), tag: b.tagName, display: getComputedStyle(b).display, visible: b.offsetParent !== null})).slice(0,10))
""")
print(f"Buttons: {buttons}", flush=True)

wasm_status = eval_js(s, 7, """
JSON.stringify({modules: WebAssembly.Module ? Array.from(document.querySelectorAll('script')).length : 0, memPages: window.__kbMem ? window.__kbMem.buffer.byteLength / 65536 : 0})
""")
print(f"WASM status: {wasm_status}", flush=True)

scripts = eval_js(s, 8, "JSON.stringify(Array.from(document.scripts).map(s => ({src: (s.src||'inline').slice(-40), id: s.id||''})).slice(0,15))")
print(f"Scripts: {scripts}", flush=True)
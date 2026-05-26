import socket, time, json, os, base64, sys

def get_page_ws():
    import urllib.request
    resp = json.loads(urllib.request.urlopen("http://127.0.0.1:9989/json", timeout=5).read())
    for p in resp:
        if "kiomet.com" in p.get("url", ""):
            return p["webSocketDebuggerUrl"]
    return resp[0]["webSocketDebuggerUrl"]

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

ws_url = get_page_ws()
s = connect(ws_url)
send_cmd(s, 1, "Runtime.enable")
time.sleep(0.5)
recv_all(s, 1)

exp = eval_js(s, 2, """
(function(){
  var e = window.__kbExports || window.__kbExp;
  if(!e) return 'no_exp';
  var names = Object.keys(e).filter(k => typeof e[k] === 'function');
  return JSON.stringify({count: names.length, sample: names.slice(0,40)});
})()""")
print(f"Exports: {exp}", flush=True)

mem = eval_js(s, 3, """
(function(){
  var m = window.__kbMem || window.__kbMemory;
  if(!m) return 'no_mem';
  return JSON.stringify({pages: m.buffer.byteLength / 65536, viewPos: m.buffer.byteLength > 0 ? 'has_view' : 'zero'});
})()""")
print(f"Memory: {mem}", flush=True)

scan = eval_js(s, 4, """
(function(){
  var m = window.__kbMem;
  if(!m) return 'no_mem';
  var b = new Uint8Array(m.buffer);
  var towers = [];
  // Scan for potential tower pattern: u16 player_id (0-4), f32 units, u8 type, f32 delay
  // Total struct ~46 bytes per Option<Tower>
  for(var offset = 0; offset < b.length - 46; offset += 4) {
    var player_id = b[offset] | (b[offset+1] << 8);
    if(player_id > 4) continue; // player_id must be 0-4
    var units_buf = new Float32Array(m.buffer.slice(offset+2, offset+6));
    var units = units_buf[0];
    if(units <= 0 || units > 100000 || units !== units) continue; // NaN check
    var type = b[offset+6];
    if(type > 3) continue; // tower type 0-3
    var delay_buf = new Float32Array(m.buffer.slice(offset+7, offset+11));
    var delay = delay_buf[0];
    if(delay < 0 || delay > 1000) continue;
    towers.push({offset: offset, player: player_id, units: Math.round(units*10)/10, type: type, delay: Math.round(delay*10)/10});
    if(towers.length >= 50) break;
  }
  return JSON.stringify({count: towers.length, towers: towers.slice(0,20)});
})()""")
print(f"Tower scan: {scan}", flush=True)

scan_gl = eval_js(s, 5, """
(function(){
  // Check if drawArrays hook exists
  var c = document.querySelector('canvas');
  if(!c) return 'no_canvas';
  var gl = c.getContext('webgl') || c.getContext('webgl2');
  if(!gl) return 'no_gl';
  var orig = gl.drawArrays;
  if(orig !== gl.drawArrays) return 'drawArrays_hooked';
  return JSON.stringify({mode: 'unhooked', vendor: gl.getParameter(gl.VENDOR), renderer: gl.getParameter(gl.RENDERER)});
})()""")
print(f"GL hook: {scan_gl}", flush=True)

ws_check = eval_js(s, 6, "JSON.stringify({readyState: window.__wsReady, wsCount: (window.__kbWS || []).length})")
print(f"WS: {ws_check}", flush=True)

kbs = eval_js(s, 7, """
JSON.stringify(Object.keys(window).filter(k => k.startsWith('__kb')).map(k => k + ': ' + typeof window[k]))
""")
print(f"__kb vars: {kbs}", flush=True)
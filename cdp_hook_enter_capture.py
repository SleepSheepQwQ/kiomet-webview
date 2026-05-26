#!/usr/bin/env python3
import socket, time, json, os, base64, sys

WS_URL = None

def get_page_ws():
    import urllib.request
    resp = urllib.request.urlopen("http://127.0.0.1:9989/json", timeout=5)
    pages = json.loads(resp.read())
    for p in pages:
        if "kiomet.com" in p.get("url", ""):
            return p["webSocketDebuggerUrl"]
    return pages[0]["webSocketDebuggerUrl"] if pages else None

def connect(ws_url):
    s = socket.socket()
    s.settimeout(15)
    s.connect(("127.0.0.1", 9989))
    path = ws_url.replace("ws://127.0.0.1:9989", "")
    key = base64.b64encode(os.urandom(16)).decode()
    s.send(f"GET {path} HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
    time.sleep(1)
    resp = s.recv(4096)
    assert b"101" in resp, f"handshake failed: {resp[:200]}"
    return s

def send_cmd(s, msg_id, method, params=None):
    payload = {"id": msg_id, "method": method}
    if params:
        payload["params"] = params
    data = json.dumps(payload).encode()
    mask = os.urandom(4)
    mdata = bytearray(len(data))
    for i in range(len(data)):
        mdata[i] = data[i] ^ mask[i & 3]
    frame = bytearray([0x81])
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
    s.send(bytes(frame))

def recv_all(s, timeout=2):
    s.settimeout(timeout)
    frames = []
    try:
        while True:
            b1 = s.recv(1)
            if not b1:
                break
            opcode = b1[0] & 0x0f
            b2 = s.recv(1)[0]
            length = b2 & 0x7f
            if length == 126:
                length = int.from_bytes(s.recv(2), 'big')
            elif length == 127:
                length = int.from_bytes(s.recv(8), 'big')
            if opcode == 0x8:
                break
            if opcode == 0x9:
                s.send(bytes([0x8a, 0x00]))
                continue
            payload = s.recv(length)
            frames.append(json.loads(payload.decode()))
    except socket.timeout:
        pass
    return frames

ws_url = get_page_ws()
print(f"Page: {ws_url}", flush=True)
s = connect(ws_url)
print("Connected", flush=True)

send_cmd(s, 1, "Runtime.enable")
time.sleep(0.5)
recv_all(s, 1)

script = """(function(){
  if(window.__kbHook) return;
  window.__kbHook = true;
  window.__kbOutgoing = [];
  window.__kbBufferData = [];

  function wrap(mod, name, orig) {
    mod[name] = function() {
      try {
        var args = [];
        for (var i = 0; i < arguments.length; i++) {
          var v = arguments[i];
          if (v === null || v === undefined) args.push(''+v);
          else if (typeof v === 'number' || typeof v === 'boolean') args.push(v);
          else if (typeof v === 'string') args.push(v.length > 100 ? v.slice(0,100)+'...' : v);
          else if (v instanceof ArrayBuffer) args.push('AB('+v.byteLength+')');
          else if (ArrayBuffer.isView(v)) args.push(v.constructor.name+'('+v.length+')');
          else args.push(typeof v);
        }
        var entry = {f: name, a: args};
        if (/__wbg_send_/.test(name)) window.__kbOutgoing.push(entry);
        else if (/__wbg_bufferData_/.test(name)) window.__kbBufferData.push(entry);
      } catch(e) {}
      return orig.apply(this, arguments);
    };
  }

  function wrapImports(imports) {
    if (!imports || typeof imports !== 'object') return;
    for (var mn of Object.getOwnPropertyNames(imports)) {
      var mod = imports[mn];
      if (!mod || typeof mod !== 'object') continue;
      for (var fn of Object.getOwnPropertyNames(mod)) {
        if (typeof mod[fn] === 'function' && /__wbg_send_|__wbg_bufferData_/.test(fn))
          wrap(mod, fn, mod[fn]);
      }
    }
  }

  var origInst = WebAssembly.instantiate;
  WebAssembly.instantiate = async function(buf, imports) {
    wrapImports(imports);
    return origInst.call(this, buf, imports);
  };

  var origStream = WebAssembly.instantiateStreaming;
  if (origStream) {
    WebAssembly.instantiateStreaming = async function(src, imports) {
      wrapImports(imports);
      return origStream.call(this, src, imports);
    };
  }

  var OrigInstance = WebAssembly.Instance;
  WebAssembly.Instance = function(mod, imports) {
    wrapImports(imports);
    return new OrigInstance(mod, imports);
  };
  WebAssembly.Instance.prototype = OrigInstance.prototype;
  window.__kbInstalled = true;
})()"""

send_cmd(s, 2, "Runtime.evaluate", {"expression": script, "awaitPromise": False})
time.sleep(0.5)
recv_all(s, 1)
print("Hook injected", flush=True)

# Now find and click "开始" button
send_cmd(s, 3, "Runtime.evaluate", {
    "expression": """
(function(){
  var btns = document.querySelectorAll('button, a, div, span');
  for(var b of btns) {
    if(b.textContent && b.textContent.trim() === '开始') {
      var r = b.getBoundingClientRect();
      return JSON.stringify({found: true, cx: Math.round(r.left + r.width/2), cy: Math.round(r.top + r.height/2), text: b.textContent.trim(), tag: b.tagName, w: Math.round(r.width), h: Math.round(r.height)});
    }
  }
  // Try buttons with common play text
  for(var b of btns) {
    if(b.textContent && (b.textContent.includes('开始') || b.textContent.includes('PLAY') || b.textContent.includes('NEW GAME'))) {
      var r = b.getBoundingClientRect();
      return JSON.stringify({found: true, cx: Math.round(r.left + r.width/2), cy: Math.round(r.top + r.height/2), text: b.textContent.trim(), tag: b.tagName, w: Math.round(r.width), h: Math.round(r.height)});
    }
  }
  return JSON.stringify({found: false});
})()""",
    "returnByValue": True,
    "awaitPromise": False
})
time.sleep(0.5)
results = recv_all(s, 2)
for r in results:
    if "result" in r and "result" in r["result"]:
        val = r["result"]["result"].get("value", "")
        print(f"Button search: {val}", flush=True)
        try:
            info = json.loads(val) if isinstance(val, str) else val
            if info.get("found"):
                cx, cy = info["cx"], info["cy"]
                print(f"Clicking at ({cx}, {cy})", flush=True)
                send_cmd(s, 4, "Input.dispatchMouseEvent", {
                    "type": "mousePressed", "x": cx, "y": cy,
                    "button": "left", "clickCount": 1
                })
                time.sleep(0.1)
                send_cmd(s, 5, "Input.dispatchMouseEvent", {
                    "type": "mouseReleased", "x": cx, "y": cy,
                    "button": "left", "clickCount": 1
                })
                time.sleep(0.1)
                recv_all(s, 1)
                print("Clicked", flush=True)
        except:
            pass


print("\nWaiting for game to load...", flush=True)
time.sleep(8)


for i in range(20):
    send_cmd(s, 100 + i, "Runtime.evaluate", {
        "expression": "JSON.stringify({out: (window.__kbOutgoing||[]).slice(), buf: (window.__kbBufferData||[]).slice()})",
        "returnByValue": True,
        "awaitPromise": False
    })
    time.sleep(1)
    results = recv_all(s, 2)
    for r in results:
        if "result" in r and "result" in r["result"]:
            val = r["result"]["result"].get("value", "{}")
            try:
                data = json.loads(val) if isinstance(val, str) else val
                if data.get("out") and len(data["out"]) > 0:
                    print(f"[{i}] OUTGOING: {len(data['out'])} captured | bufData: {len(data.get('buf',[]))}", flush=True)
                    for m in data["out"][:3]:
                        print(f"  send: {m['f']} args={m['a']}", flush=True)
                    if data.get("buf"):
                        for m in data["buf"][:2]:
                            print(f"  bufferData: {m['a']}", flush=True)
            except:
                pass
    time.sleep(2)

print("\nDone polling", flush=True)
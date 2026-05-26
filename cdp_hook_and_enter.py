#!/usr/bin/env python3
"""Hook WebAssembly.instantiate on current page, then click 开始 to enter game."""
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

def recv_all(s, timeout=5):
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
print("Connected to page CDP", flush=True)


send_cmd(s, 1, "Runtime.enable")
time.sleep(0.5)
recv_all(s, 1)

HOOK_JS = """
(function(){
  if(window.__kbHook) return;
  window.__kbHook = true;
  window.__kbOutgoing = [];
  window.__kbBufferData = [];
  window.__kbClicks = [];

  function wrap(mod, name, orig) {
    mod[name] = function() {
      try {
        var args = [];
        for (var i = 0; i < arguments.length; i++) {
          var v = arguments[i];
          if (v === null || v === undefined) args.push('' + v);
          else if (typeof v === 'number' || typeof v === 'boolean') args.push(v);
          else if (typeof v === 'string') args.push(v.length > 100 ? v.slice(0,100) + '...' : v);
          else if (v instanceof ArrayBuffer) args.push('AB(' + v.byteLength + ')');
          else if (ArrayBuffer.isView(v)) args.push(v.constructor.name + '(' + v.length + ')');
          else args.push(typeof v);
        }
        var entry = {f: name, a: args};
        if (/__wbg_send_/.test(name)) {
          window.__kbOutgoing.push(entry);
        } else if (/__wbg_bufferData_/.test(name)) {
          window.__kbBufferData.push(entry);
        } else if (/__wbg_client(X|Y)_/.test(name)) {
          window.__kbClicks.push(entry);
        }
        console.log('KB_WRAP', JSON.stringify(entry));
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
        if (typeof mod[fn] === 'function' &&
            /__wbg_send_|__wbg_client(X|Y)_|__wbg_bufferData_/.test(fn)) {
          wrap(mod, fn, mod[fn]);
        }
      }
    }
  }

  // Hook WebAssembly.instantiate
  var origInst = WebAssembly.instantiate;
  WebAssembly.instantiate = async function(buf, imports) {
    wrapImports(imports);
    return origInst.call(this, buf, imports);
  };

  // Hook WebAssembly.instantiateStreaming
  var origStream = WebAssembly.instantiateStreaming;
  if (origStream) {
    WebAssembly.instantiateStreaming = async function(src, imports) {
      wrapImports(imports);
      return origStream.call(this, src, imports);
    };
  }

  // Also hook WebAssembly.Instance constructor for fallback
  var OrigInstance = WebAssembly.Instance;
  WebAssembly.Instance = function(mod, imports) {
    wrapImports(imports);
    return new OrigInstance(mod, imports);
  };
  WebAssembly.Instance.prototype = OrigInstance.prototype;

  console.log('KB_HOOK_INSTALLED');
})();
"""


send_cmd(s, 2, "Runtime.evaluate", {
    "expression": HOOK_JS,
    "awaitPromise": False
})
time.sleep(1)
results = recv_all(s, 2)
for r in results:
    print(f"  Hook result: {json.dumps(r, indent=2)[:300]}", flush=True)

print("\nHook injected. Now waiting for you to click '开始' manually.", flush=True)
print("Captured calls will appear below. Press Ctrl+C to stop.", flush=True)


try:
    while True:
        time.sleep(3)

        send_cmd(s, 100, "Runtime.evaluate", {
            "expression": "JSON.stringify({out: window.__kbOutgoing.splice(0), buf: window.__kbBufferData.splice(0), clk: window.__kbClicks.splice(0)})",
            "awaitPromise": False,
            "returnByValue": False
        })
        time.sleep(1)
        results = recv_all(s, 3)
        for r in results:
            if "result" in r and "result" in r["result"]:
                try:
                    val = r["result"]["result"].get("value", "{}")
                    data = json.loads(val)
                    if data.get("out"):
                        print(f"[OUTGOING] {len(data['out'])} msgs", flush=True)
                        for m in data["out"][:5]:
                            print(f"  send: args={m['a']}", flush=True)
                    if data.get("buf"):
                        print(f"[BUFFER] {len(data['buf'])} calls", flush=True)
                        for m in data["buf"][:3]:
                            print(f"  bufferData: {m['a']}", flush=True)
                    if data.get("clk"):
                        print(f"[CLICK] {len(data['clk'])} reads", flush=True)
                        for m in data["clk"][:3]:
                            print(f"  click: {m['a']}", flush=True)
                except:
                    pass

except KeyboardInterrupt:
    print("\nStopped.", flush=True)


"""Find WASM memory and tower data from the running game."""
import socket, time, json, os, base64, sys

def get_ws():
    import urllib.request
    resp = json.loads(urllib.request.urlopen("http://127.0.0.1:9989/json", timeout=5).read())
    return next(p["webSocketDebuggerUrl"] for p in resp if "kiomet.com" in p.get("url",""))

s = socket.socket(); s.settimeout(30)
s.connect(("127.0.0.1", 9989))
path = get_ws().replace("ws://127.0.0.1:9989", "")
key = base64.b64encode(os.urandom(16)).decode()
s.send(f"GET {path} HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
time.sleep(1); s.recv(4096)

def send(mid, method, params=None):
    p = {"id": mid, "method": method}
    if params: p["params"] = params
    data = json.dumps(p).encode(); mask = os.urandom(4); md = bytearray(len(data))
    for i in range(len(data)): md[i] = data[i] ^ mask[i & 3]
    f = bytearray([0x81]); L = len(data)
    if L < 126: f.append(0x80 | L)
    elif L < 65536: f.append(0x80 | 126); f.extend(L.to_bytes(2, "big"))
    else: f.append(0x80 | 127); f.extend(L.to_bytes(8, "big"))
    f += bytearray(mask) + bytearray(md); s.send(bytes(f))

def recv(timeout=2):
    s.settimeout(timeout); frames = []
    try:
        while True:
            b1 = s.recv(1); oc = b1[0]&0x0f; b2 = s.recv(1)[0]; L = b2&0x7f
            if L==126: L=int.from_bytes(s.recv(2),"big")
            elif L==127: L=int.from_bytes(s.recv(8),"big")
            if oc==0x8: break
            if oc==0x9: s.send(bytes([0x8a,0x00])); continue
            frames.append(json.loads(s.recv(L).decode()))
    except: pass
    return frames

def js(expr):
    send(99, "Runtime.evaluate", {"expression": expr, "returnByValue": True})
    time.sleep(0.5)
    for r in recv():
        if "result" in r and "result" in r["result"]:
            return r["result"]["result"].get("value")

send(1, "Runtime.enable"); time.sleep(0.3); recv()


print("__kbExp type:", js("typeof window.__kbExp"), flush=True)
print("__kbExp keys:", js("JSON.stringify(Object.getOwnPropertyNames(window.__kbExp||{}))"), flush=True)
print("__kbMem type:", js("typeof window.__kbMem"), flush=True)
print("__kbMem buffer:", js("window.__kbMem ? (typeof window.__kbMem.buffer) + ' ' + (window.__kbMem.buffer ? window.__kbMem.buffer.byteLength : 'null') : 'none'"), flush=True)


print("\nmemory via exp.memory:", js("""
(function(){
  try {
    var m = window.__kbExp.memory;
    return m ? 'exists ' + m.buffer.byteLength : 'no_memory';
  } catch(e) { return 'err'; }
})()"""), flush=True)


print("__kbMem byteLength:", js("window.__kbMem ? window.__kbMem.length || window.__kbMem.byteLength || 'no_len' : 'none'"), flush=True)


print("__kbMem buffer view:", js("""
(function(){
  try {
    var m = window.__kbMem;
    if(!m) return 'no_mem';
    // Try to read from it
    var v = new Uint8Array(m.buffer || m);
    return v.length;
  } catch(e) { return 'err:' + String(e); }
})()"""), flush=True)


print("__kbMem constructor:", js("window.__kbMem ? window.__kbMem.constructor.name : 'none'"), flush=True)


print("\nGL buffer memory:", js("""
(function(){
  var c = document.querySelector('canvas');
  if(!c) return 'no_canvas';
  var gl = c.getContext('webgl');
  if(!gl) return 'no_gl';
  // Try to read the vertex buffer data
  // The game uploads tower vertex data to GL buffers
  // If we can read these, we can find tower positions
  try {
    var b = gl.getParameter(gl.ARRAY_BUFFER_BINDING);
    if(b) {
      var buf = new Uint8Array(4096);
      gl.getBufferSubData(gl.ARRAY_BUFFER, 0, buf);
      return 'got_buffer ' + buf[0] + ' ' + buf[1] + ' ' + buf[2];
    }
    return 'no_binding';
  } catch(e) { return 'err:' + String(e); }
})()"""), flush=True)


print("\nFinding wasm memory via known offsets:", js("""
(function(){
  try {
    var u8 = new Uint8Array(4096);
    // Try to read WASM memory through getBufferSubData
    // The WebGL driver internally references WASM memory
    // When the game uploads data via bufferData(gpu_buffer, wasm_ptr, ...)
    // the bufferData intercept doesn't work, but the data IS in the GPU
    // We can read it back if we know the buffer handle

    // Try reading GL state for all currently bound buffers
    var c = document.querySelector('canvas');
    var gl = c.getContext('webgl');
    var bufs = {};
    var ALL_BINDINGS = [gl.ARRAY_BUFFER, gl.ELEMENT_ARRAY_BUFFER];
    for(var t of ALL_BINDINGS) {
      var b = gl.getParameter(t);
      if(b) bufs[t] = b;
    }
    return JSON.stringify({bindingCount: Object.keys(bufs).length});
  } catch(e) { return String(e); }
})()"""), flush=True)


print("\nPlayer state:", js("""
(function(){
  var t = document.body ? document.body.innerText : '';
  // Extract player rank and units
  var m = t.match(/UnderAguest[\\t\\s]*(\\d+)/);
  if(m) return 'units=' + m[1];
  return 'no_match';
})()"""), flush=True)
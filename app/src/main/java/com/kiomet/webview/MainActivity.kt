package com.kiomet.webview

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.Process
import android.view.View
import android.webkit.*
import android.widget.*
import android.util.Log
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import java.net.URL
import java.net.HttpURLConnection

class MainActivity : AppCompatActivity() {
    private lateinit var webView: WebView
    private var bridgeServer: BridgeServer? = null
    private var cdpBridge: CDPBridge? = null
    private val handler = Handler(Looper.getMainLooper())

companion object {
        private const val WASM_HOOK = """
var _kbCap = function() { if (window.__kbWm.length > 100000) window.__kbWm.splice(0, 50000); };
window.__kbWm = [];
window.__kbMem = null;
window.__kbExp = null;

// Patch getContext to intercept WebGL context + install coordinate calculator
var _origGC = HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext = function(type) {
    var ctx = _origGC.apply(this, arguments);
    if (type.indexOf('webgl') === 0 && ctx && !ctx.__kbPatch) {
        ctx.__kbPatch = true;
        // Coordinate calculator state (exposed globally for CDP debugging)
        var _mat = null;
        var _texData = null;
        window.__kbDebugState = {mat: null, texLen: 0, drawCount: 0, lastError: null};

        var _u3Orig = ctx.uniformMatrix3fv;
        if (_u3Orig) {
            ctx.uniformMatrix3fv = function(loc, trans, val) {
                if (val && val.length === 9) { _mat = Array.from(val); window.__kbDebugState.mat = _mat; }
                return _u3Orig.apply(this, arguments);
            };
        }

        var _u4Orig = ctx.uniformMatrix4fv;
        if (_u4Orig) {
            ctx.uniformMatrix4fv = function(loc, trans, val) {
                if (val && val.length === 16) {
                    // Extract 3x3 from 4x4
                    _mat = [val[0],val[1],val[2], val[4],val[5],val[6], val[8],val[9],val[10]];
                    window.__kbDebugState.mat = _mat;
                }
                return _u4Orig.apply(this, arguments);
            };
        }

        var _tOrig = ctx.texSubImage2D;
        if (_tOrig) {
            ctx.texSubImage2D = function() {
                var px = arguments[8];
                if (px && px.byteLength) {
                    var u8 = new Uint8Array(px.byteLength > 2048 ? px.slice(0, 2048) : px);
                    _texData = Array.from(u8);
                    window.__kbDebugState.texLen = _texData.length;
                }
                return _tOrig.apply(this, arguments);
            };
        }

        var _dOrig = ctx.drawElements;
        if (_dOrig) {
            ctx.drawElements = function(mode, count, type, offset) {
                if (_mat && _texData && _texData.length > 10) {
                    try {
                        window.__kbDebugState.drawCount++;
                        var a=_mat[0], g=_mat[6], e=_mat[4], h=_mat[7];
                        var vpW=1218, vpH=1950, dpr=3;
                        var camWX=-g/a, camWY=-h/e;
                        var gridCX=Math.round(camWX/5), gridCY=Math.round(camWY/5);
                        var pixCnt=Math.floor(_texData.length/4);
                        var texW=Math.round(Math.sqrt(pixCnt)), texH=Math.ceil(pixCnt/texW);
                        var startX=gridCX-Math.floor(texW/2), startY=gridCY-Math.floor(texH/2);
                        var towers=[];
                        var typeCache = window.__kbTowerPositionsWithTypes || [];
                        for(var i=0;i<pixCnt;i++){
                          var off=i*4;
                          if(_texData[off]===0x7f) continue;
                          var id=_texData[off+2], vis=_texData[off+3];
                          if(vis!==255) continue;
                          var txx=i%texW, txy=Math.floor(i/texW);
                          var wx=(startX+txx)*5+2.5, wy=(startY+txy)*5+2.5;
                          var scrX=((a*wx+g)+1)*0.5/dpr*vpW+3, scrY=((e*wy+h)+1)*0.5/dpr*vpH+3;
                          var gridMatch = null;
                          for (var ci = 0; ci < typeCache.length; ci++) {
                            var ct = typeCache[ci];
                            if (ct.w && ct.w[0] === Math.round(wx) && ct.w[1] === Math.round(wy) && ct.type >= 0) {
                              gridMatch = ct.type;
                              break;
                            }
                          }
                          towers.push({s:[Math.round(scrX),Math.round(scrY)],id:id,w:[Math.round(wx),Math.round(wy)],type:gridMatch !== null ? gridMatch : -1});
                        }
                        if (towers.length > 0) window.__kbTowerPositions = towers;
                    } catch(e) { window.__kbDebugState.lastError = e.message; }
                }
                return _dOrig.apply(this, arguments);
            };
        }

        // Log all WebGL calls to __kbWm
        var targets = ['drawArrays','drawElements','texSubImage2D','texImage2D','uniform4fv','uniformMatrix4fv','bufferData','bufferSubData'];
        targets.forEach(function(name) {
            var orig = ctx[name];
            if (!orig) return;
            ctx[name] = (function(n, o) {
                return function() {
                    try {
                        var info = {f:n, t:Date.now()};
                        if ((n.indexOf('tex') === 0 || n.indexOf('buffer') === 0) && arguments.length > 1 && arguments[arguments.length-1]) {
                            var data = arguments[arguments.length-1];
                            if (data.byteLength) {
                                var view = new Uint8Array(data.byteLength > 128 ? data.slice(0,128) : data);
                                info.d = Array.from(view).map(function(x){return ('0'+x.toString(16)).slice(-2)}).join('');
                                info.n = data.byteLength;
                            } else if (data.length) {
                                info.v = Array.from(data).slice(0,16);
                            }
                        } else if (n.indexOf('uniform') === 0 && arguments.length > 1) {
                            info.v = Array.from(arguments[1] || []).slice(0,8);
                        }
                        window.__kbWm.push(info);
                        _kbCap();
                    } catch(e) {}
                    return o.apply(this, arguments);
                };
            })(name, orig);
        });
    }
    return ctx;
};

var _callCount = 0;
function _wrapImport(i) {
    if (!i || typeof i !== 'object') return;
    Object.keys(i).forEach(function(mn) {
        var m = i[mn];
        if (!m || typeof m !== 'object') return;
        Object.keys(m).forEach(function(fn) {
            if (fn.indexOf('__wbg_') !== 0) return;
            var orig = m[fn];
            var isRender = fn.indexOf('send') > 0 || fn.indexOf('bufferData') > 0 || fn.indexOf('clientX') > 0 || fn.indexOf('clientY') > 0 || fn.indexOf('texImage') > 0 || fn.indexOf('texSubImage') > 0 || fn.indexOf('drawArrays') > 0 || fn.indexOf('drawElements') > 0 || fn.indexOf('uniform') > 0;
            var isExplorer = !isRender && fn.indexOf('drawElements_') < 0;
            m[fn] = function() {
                try {
                    if (isRender) {
                        var info = {f:fn, t:Date.now()};
                        var last = arguments.length - 1;
                        if (last >= 0) {
                            var v = arguments[last];
                            if (v && v.byteLength) {
                                var u8 = new Uint8Array(v.byteLength > 64 ? v.slice(0, 64) : v);
                                info.d = Array.from(u8).map(function(x){return ('0'+x.toString(16)).slice(-2)}).join('');
                                info.n = v.byteLength;
                            } else if (v && v.length) {
                                info.v = Array.from(v).slice(0, 16);
                            } else if (typeof v === 'number') {
                                info.v = v;
                            }
                        }
                        window.__kbWm.push(info);
                        _kbCap();
                    }
                    if (isExplorer && _callCount < 5000) {
                        _callCount++;
                        var arg0 = arguments[0];
                        var log = {n:fn, t:Date.now()};
                        if (typeof arg0 === 'number') log.v0 = arg0;
                        else if (arg0 && arg0.byteLength) {
                            var u8 = new Uint8Array(arg0.byteLength > 32 ? arg0.slice(0,32) : arg0);
                            log.d0 = Array.from(u8).map(function(x){return ('0'+x.toString(16)).slice(-2)}).join('');
                        }
                        window.__kbCallLog.push(log);
                    }
                } catch(e) {}
                return orig.apply(this, arguments);
            };
        });
    });
}
var _ii = WebAssembly.instantiate;
WebAssembly.instantiate = function(b, i) { _wrapImport(i); return _ii.call(this, b, i).then(function(r) { var inst = r instanceof WebAssembly.Instance ? r : r.instance; if (inst && inst.exports) { if (inst.exports.memory) window.__kbMem = inst.exports.memory; window.__kbExp = inst.exports; } return r; }); };
var _iis = WebAssembly.instantiateStreaming;
if (_iis) { WebAssembly.instantiateStreaming = function(s, i) { _wrapImport(i); return _iis.call(this, s, i).then(function(r) { var inst = r instanceof WebAssembly.Instance ? r : r.instance; if (inst && inst.exports) { if (inst.exports.memory) window.__kbMem = inst.exports.memory; window.__kbExp = inst.exports; } return r; }); }; }

var _wsSend = WebSocket.prototype.send;
Object.defineProperty(WebSocket.prototype, 'send', {
    configurable: true, writable: true,
    value: function(data) {
        if (data && data.byteLength) {
            var view = new Uint8Array(data);
            window.__kbWm.push({f:'wsSend', d:Array.from(view).map(function(x){return ('0'+x.toString(16)).slice(-2)}).join(''), n:data.byteLength, t:Date.now()});
        }
        return _wsSend.call(this, data);
    }
});

window.__kbRawMessages = [];
var _origAddEventListener = WebSocket.prototype.addEventListener;
WebSocket.prototype.addEventListener = function(type, handler) {
    if (type === 'message') {
        var _origHandler = handler;
        handler = function(event) {
            if (event.data && event.data.byteLength) {
                try {
                    var buf = event.data;
                    var view = new Uint8Array(buf.byteLength > 4096 ? buf.slice(0, 4096) : buf);
                    var hex = Array.from(view).map(function(x){return ('0'+x.toString(16)).slice(-2)}).join('');
                    window.__kbRawMessages.push({d:hex, n:buf.byteLength, t:Date.now()});
                    if (window.__kbRawMessages.length > 10) window.__kbRawMessages.shift();
                } catch(e){}
            }
            return _origHandler.apply(this, arguments);
        };
    }
    return _origAddEventListener.call(this, type, handler);
};

window.__kbCallLog = [];

// Enhanced WASM memory scanner using chunk-based tower layout
// Each Chunk has 256 towers (16x16 grid), stored as contiguous Option<Tower> entries.
// World is 32x32 chunks = 1024 chunks total.
// World grid 512x512, each cell = 5 world units.
window.__kbScanMemoryForTypes = function() {
  if (!window.__kbMem || !window.__kbTowerPositions || window.__kbTowerPositions.length === 0) return null;
  var mem = window.__kbMem;
  var towers = window.__kbTowerPositions;
  var maxBytes = Math.min(mem.buffer.byteLength, 64 * 1024 * 1024);
  var arr = new Uint8Array(mem.buffer, 0, maxBytes);
  var enriched = [];
  var CHUNK_TOWERS = 256;
  var TYPE_OFFSET = 4;
  var stride = 16;
  var chunkBytes = stride * CHUNK_TOWERS;

  for (var ti = 0; ti < towers.length; ti++) {
    var tw = towers[ti];
    if (!tw.w) continue;
    var gx = tw.w[0], gy = tw.w[1];
    var localIdx = (gy % 16) * 16 + (gx % 16);
    var found = null;

    for (var chunkStart = 0; chunkStart + chunkBytes <= maxBytes; chunkStart += chunkBytes) {
      var valid = 0;
      for (var j = 0; j < CHUNK_TOWERS; j++) {
        var off = chunkStart + j * stride;
        var disc = arr[off];
        if (disc !== 0 && disc !== 1) { valid = -1; break; }
        if (disc === 1) {
          var tv = arr[off + TYPE_OFFSET];
          if (tv >= 0 && tv < 27) valid++;
          else { valid = -1; break; }
        }
      }
      if (valid > 200) {
        var tv = arr[chunkStart + localIdx * stride + TYPE_OFFSET];
        if (tv >= 0 && tv < 27) {
          found = {offset: chunkStart + localIdx * stride + TYPE_OFFSET, type: tv, stride: stride, chunkValid: valid};
          break;
        }
      }
    }
    enriched.push({
      s: tw.s, w: tw.w, id: tw.id,
      type: found ? found.type : -1,
      stride: found ? found.stride : 0,
      offset: found ? found.offset : -1
    });
  }
  window.__kbTowerPositionsWithTypes = enriched;
  return enriched;
};

(function(){
  var canvas = document.querySelector('canvas');
  if(!canvas) return;
  var gl = canvas.getContext('webgl');
  if(!gl) return;
  var _mat = null;
  var _texData = null;

  var _origUni = gl.uniformMatrix3fv;
  gl.uniformMatrix3fv = function(loc, trans, val) {
    if(val && val.length === 9) _mat = Array.from(val);
    return _origUni.apply(this, arguments);
  };

  var _origTex = gl.texSubImage2D;
  gl.texSubImage2D = function() {
    var px = arguments[8];
    if(px && px.byteLength) {
      var u8 = new Uint8Array(px.byteLength > 2048 ? px.slice(0, 2048) : px);
      _texData = Array.from(u8);
    }
    return _origTex.apply(this, arguments);
  };

  var _origDraw = gl.drawElements;
  gl.drawElements = function(mode, count, type, offset) {
    if(_mat && _texData) {
try {
        var a=_mat[0], g=_mat[6], e=_mat[4], h=_mat[7];
        var vpW=1218, vpH=1950, dpr=3;
        var camWX=-g/a, camWY=-h/e;
        var gridCX=Math.round(camWX/5), gridCY=Math.round(camWY/5);
        var pixCnt=Math.floor(_texData.length/4);
        var texW=Math.round(Math.sqrt(pixCnt)), texH=Math.ceil(pixCnt/texW);
        var startX=gridCX-Math.floor(texW/2), startY=gridCY-Math.floor(texH/2);
        var towers=[];
        var typeCache = window.__kbTowerPositionsWithTypes || [];
        for(var i=0;i<pixCnt;i++){
          var off=i*4;
          if(_texData[off]===0x7f) continue;
          var id=_texData[off+2], vis=_texData[off+3];
          if(vis!==255) continue;
          var txx=i%texW, txy=Math.floor(i/texW);
          var wx=(startX+txx)*5+2.5, wy=(startY+txy)*5+2.5;
          var scrX=((a*wx+g)+1)*0.5/dpr*vpW+3, scrY=((e*wy+h)+1)*0.5/dpr*vpH+3;
          var gridMatch = null;
          for (var ci = 0; ci < typeCache.length; ci++) {
            var ct = typeCache[ci];
            if (ct.w && ct.w[0] === Math.round(wx) && ct.w[1] === Math.round(wy) && ct.type >= 0) {
              gridMatch = ct.type;
              break;
            }
          }
          towers.push({s:[Math.round(scrX),Math.round(scrY)],id:id,w:[Math.round(wx),Math.round(wy)],type:gridMatch !== null ? gridMatch : -1});
        }
        window.__kbTowerPositions = towers;
      } catch(e) {}
    }
    return _origDraw.apply(this, arguments);
  };
})();
"""
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WebView.setWebContentsDebuggingEnabled(true)

        WindowCompat.setDecorFitsSystemWindows(window, false)
        window.attributes.layoutInDisplayCutoutMode =
            android.view.WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS

        setContentView(R.layout.activity_main)
        webView = findViewById(R.id.webView)
        val refreshBtn = findViewById<ImageButton>(R.id.refreshBtn)
        val settingsBtn = findViewById<ImageButton>(R.id.settingsBtn)
        val statusBadge = findViewById<TextView>(R.id.statusBadge)

        WindowInsetsControllerCompat(window, webView).let { c ->
            c.hide(WindowInsetsCompat.Type.systemBars())
            c.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }

        val prefs = getSharedPreferences("bridge", MODE_PRIVATE)
        var port = prefs.getInt("port", 9988)

        startBridge(port)
        startCDPBridge(port)
        setupWebView(port)
        statusBadge.text = ":$port"
        statusBadge.visibility = View.VISIBLE

        refreshBtn.setOnClickListener { webView.reload() }

        settingsBtn.setOnClickListener {
            showPortDialog { newPort ->
                port = newPort
                prefs.edit().putInt("port", port).apply()
                bridgeServer?.stop()
                cdpBridge?.stop()
                startBridge(port)
                startCDPBridge(port)
                statusBadge.text = ":$port"
                webView.reload()
            }
        }

        webView.loadUrl("https://kiomet.com")
    }

    private fun startBridge(port: Int) {
        bridgeServer = BridgeServer(port)
        bridgeServer!!.start()
    }

    private fun startCDPBridge(bridgePort: Int) {
        val cdp = CDPBridge(bridgePort + 1)
        cdpBridge = cdp
        cdp.start()
    }

    private fun showPortDialog(onSet: (Int) -> Unit) {
        val input = EditText(this).apply {
            setText(getSharedPreferences("bridge", MODE_PRIVATE).getInt("port", 9988).toString())
            inputType = android.text.InputType.TYPE_CLASS_NUMBER
        }
        AlertDialog.Builder(this)
            .setTitle("Bridge Port")
            .setView(input)
            .setPositiveButton("OK") { _, _ ->
                val p = input.text.toString().toIntOrNull() ?: 9988
                onSet(p.coerceIn(1024, 65535))
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun setupWebView(port: Int) {
        val s = webView.settings
        s.javaScriptEnabled = true
        s.domStorageEnabled = true
        s.databaseEnabled = true
        s.allowFileAccess = true
        s.allowContentAccess = true
        s.mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
        s.cacheMode = WebSettings.LOAD_DEFAULT
        s.builtInZoomControls = true
        s.displayZoomControls = false

        // 原生JS桥 - 不受CORS限制，跨页面持久化
        webView.addJavascriptInterface(BridgeInterface(), "KB")

        webView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView, url: String, favicon: android.graphics.Bitmap?) {
                super.onPageStarted(view, url, favicon)
                injectWithRetry(view, port, 30, 500)
            }
            override fun onPageFinished(view: WebView, url: String) {
                injectWithRetry(view, port, 10, 300)
                Log.i("KB", "Page loaded: $url")
            }
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                val url = request.url.toString()
                if (url.endsWith("client.js")) {
                    try {
                        val conn = URL(url).openConnection() as HttpURLConnection
                        conn.connectTimeout = 5000
                        conn.readTimeout = 5000
                        val original = conn.inputStream.readBytes()
                        conn.disconnect()
                        val combined = WASM_HOOK.toByteArray(Charsets.UTF_8) + original
                        Log.i("KB", "Injected WASM hook into client.js")
                        return WebResourceResponse("application/javascript", "utf-8", combined.inputStream())
                    } catch (e: Exception) {
                        Log.e("KB", "Intercept failed: ${e.message}")
                    }
                }
                
                return super.shouldInterceptRequest(view, request)
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(msg: ConsoleMessage): Boolean {
                Log.i("KB", "${msg.message()} (${msg.sourceId()}:${msg.lineNumber()})")
                return true
            }
        }
    }

    private fun injectWithRetry(view: WebView, port: Int, attempts: Int, delayMs: Long) {
        val script = InjectedScript.CODE.replace("9988", port.toString())
        var remaining = attempts
        fun retry() {
            view.evaluateJavascript(script) { result ->
                if ((result.isNullOrEmpty() || result == "null") && remaining > 0) {
                    remaining--
                    handler.postDelayed({ retry() }, delayMs)
                } else if (result != null && result != "null") {
                    Log.i("KB", "Script injected OK")
                }
            }
        }
        retry()
    }

    override fun onBackPressed() {
        if (webView.canGoBack()) webView.goBack() else super.onBackPressed()
    }

    override fun onDestroy() {
        bridgeServer?.stop()
        cdpBridge?.stop()
        super.onDestroy()
    }

    inner class BridgeInterface {
        @android.webkit.JavascriptInterface
        fun send(type: String, json: String) {
            Log.i("KB", "JS-$type: ${json.take(200)}")
            bridgeServer?.let { bs ->
                when (type) {
                    "data" -> bs.addMessage(json)
                    "click" -> bs.addClick(json)
                    "log" -> Log.i("KB", "JS-log: $json")
                    "ping" -> Log.i("KB", "JS-ping: $json")
                }
            }
        }
    }
}
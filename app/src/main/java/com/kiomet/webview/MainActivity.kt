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
window.__kbWm = [];
window.__kbMem = null;
window.__kbExp = null;

// Patch getContext to intercept WebGL context at creation time
var _origGC = HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext = function(type) {
    var ctx = _origGC.apply(this, arguments);
    if (type.indexOf('webgl') === 0 && ctx && !ctx.__kbPatch) {
        ctx.__kbPatch = true;
        // Patch all relevant WebGL methods on the INSTANCE
        var targets = ['drawArrays','drawElements','texSubImage2D','texImage2D','uniform4fv','uniformMatrix4fv','bufferData','bufferSubData'];
        targets.forEach(function(name) {
            var orig = ctx[name];
            if (!orig) return;
            ctx[name] = function() {
                try {
                    var info = {f:name, t:Date.now()};
                    if ((name.indexOf('tex') === 0 || name.indexOf('buffer') === 0) && arguments.length > 1 && arguments[arguments.length-1]) {
                        var data = arguments[arguments.length-1];
                        if (data.byteLength) {
                            var view = new Uint8Array(data.byteLength > 128 ? data.slice(0,128) : data);
                            info.d = Array.from(view).map(function(x){return ('0'+x.toString(16)).slice(-2)}).join('');
                            info.n = data.byteLength;
                        } else if (data.length) {
                            info.v = Array.from(data).slice(0,16);
                        }
                    } else if (name.indexOf('uniform') === 0 && arguments.length > 1) {
                        info.v = Array.from(arguments[1] || []).slice(0,8);
                    }
                    window.__kbWm.push(info);
                } catch(e) {}
                return orig.apply(this, arguments);
            };
        });
    }
    return ctx;
};

// Backup: wrap WASM import functions at instantiation time
function _wrapImport(i) {
    if (!i || typeof i !== 'object') return;
    Object.keys(i).forEach(function(mn) {
        var m = i[mn];
        if (!m || typeof m !== 'object') return;
        Object.keys(m).forEach(function(fn) {
            if (fn.indexOf('__wbg_') !== 0) return;
            if (fn.indexOf('send') > 0 || fn.indexOf('bufferData') > 0 || fn.indexOf('clientX') > 0 || fn.indexOf('clientY') > 0 || fn.indexOf('texImage') > 0 || fn.indexOf('texSubImage') > 0 || fn.indexOf('drawArrays') > 0 || fn.indexOf('drawElements') > 0 || fn.indexOf('uniform') > 0) {
                var orig = m[fn];
                m[fn] = function() {
                    try {
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
                    } catch(e) {}
                    return orig.apply(this, arguments);
                };
            }
        });
    });
}
var _ii = WebAssembly.instantiate;
WebAssembly.instantiate = function(b, i) { _wrapImport(i); return _ii.call(this, b, i).then(function(r) { var inst = r instanceof WebAssembly.Instance ? r : r.instance; if (inst && inst.exports) { if (inst.exports.memory) window.__kbMem = inst.exports.memory; window.__kbExp = inst.exports; } return r; }); };
var _iis = WebAssembly.instantiateStreaming;
if (_iis) { WebAssembly.instantiateStreaming = function(s, i) { _wrapImport(i); return _iis.call(this, s, i).then(function(r) { var inst = r instanceof WebAssembly.Instance ? r : r.instance; if (inst && inst.exports) { if (inst.exports.memory) window.__kbMem = inst.exports.memory; window.__kbExp = inst.exports; } return r; }); }; }

// Hook WebSocket.send for outgoing command capture
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

// Coordinate calculator: runs at draw time to calculate tower screen positions
window.__kbTowerPositions = [];
(function(){
  var canvas = document.querySelector('canvas');
  if(!canvas) return;
  var gl = canvas.getContext('webgl');
  if(!gl) return;
  var _mat = null;
  var _texData = null;
  var _texN = 0;
  
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
      _texN = px.byteLength;
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
        for(var i=0;i<pixCnt;i++){
          var off=i*4;
          if(_texData[off]===0x7f) continue;
          var id=_texData[off+2], vis=_texData[off+3];
          if(vis!==255) continue;
          var txx=i%texW, txy=Math.floor(i/texW);
          var wx=(startX+txx)*5+2.5, wy=(startY+txy)*5+2.5;
          var scrX=((a*wx+g)+1)*0.5/dpr*vpW+3, scrY=((e*wy+h)+1)*0.5/dpr*vpH+3;
          towers.push({s:[Math.round(scrX),Math.round(scrY)],id:id,w:[Math.round(wx),Math.round(wy)]});
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
                if (url.endsWith("client_bg.wasm")) {
                    try {
                        val wasmStream = assets.open("kiomet_bg.wasm")
                        Log.i("KB", "Serving patched WASM (${wasmStream.available()} bytes)")
                        return WebResourceResponse("application/wasm", null, wasmStream)
                    } catch (e: Exception) {
                        Log.e("KB", "WASM intercept failed: ${e.message}")
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
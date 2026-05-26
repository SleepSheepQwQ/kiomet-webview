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
            var orig = m[fn];
            m[fn] = function() {
                try { window.__kbWm.push({f:fn, t:Date.now()}); } catch(e) {}
                return orig.apply(this, arguments);
            };
        });
    });
}
var _ii = WebAssembly.instantiate;
WebAssembly.instantiate = function(b, i) { _wrapImport(i); return _ii.call(this, b, i); };
var _iis = WebAssembly.instantiateStreaming;
if (_iis) { WebAssembly.instantiateStreaming = function(s, i) { _wrapImport(i); return _iis.call(this, s, i); }; }

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
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
window.__kbMem = null;
window.__kbExp = null;
window.__kbTowers = [];

var _ii = WebAssembly.instantiate;
WebAssembly.instantiate = function(b, i) {
    return _ii.call(this, b, i).then(function(r) {
        var inst = r instanceof WebAssembly.Instance ? r : r.instance;
        if (inst && inst.exports && inst.exports.memory) {
            window.__kbMem = inst.exports.memory;
            window.__kbExp = inst.exports;
        }
        return r;
    });
};
var _iis = WebAssembly.instantiateStreaming;
if (_iis) {
    WebAssembly.instantiateStreaming = function(s, i) {
        return _iis.call(this, s, i).then(function(r) {
            var inst = r instanceof WebAssembly.Instance ? r : r.instance;
            if (inst && inst.exports && inst.exports.memory) {
                window.__kbMem = inst.exports.memory;
                window.__kbExp = inst.exports;
            }
            return r;
        });
    };
}

// Hook the game's WebGL rendering to capture tower draw calls
var _gl = WebGLRenderingContext.prototype;
var _unif4fv = _gl.uniform4fv;
_gl.uniform4fv = function(loc, v) {
    if (v && v.length >= 4) {
        var x = v[0], y = v[1], z = v[2];
        if (Math.abs(x) < 10000 && Math.abs(y) < 10000) {
            window.__kbLastPos = [x, y, z];
        }
    }
    return _unif4fv.apply(this, arguments);
};
var _drawA = _gl.drawArrays;
_gl.drawArrays = function(mode, first, count) {
    if (mode === 4 && count > 2 && count < 200 && window.__kbLastPos) {
        var pos = window.__kbLastPos;
        var found = false;
        var arr = window.__kbTowers;
        for (var i = 0; i < arr.length; i++) {
            if (Math.abs(arr[i][0] - pos[0]) < 0.01 && Math.abs(arr[i][1] - pos[1]) < 0.01) {
                found = true; break;
            }
        }
        if (!found && arr.length < 100) {
            arr.push([pos[0], pos[1], pos[2], Date.now()]);
        }
    }
    window.__kbLastPos = null;
    return _drawA.apply(this, arguments);
};

// Hook WebSocket send (now with correct timing)
var _wsSend = WebSocket.prototype.send;
Object.defineProperty(WebSocket.prototype, 'send', {
    configurable: true, writable: true,
    value: function(data) {
        if (data && data.byteLength) {
            var view = new Uint8Array(data);
            window.__kbLastSend = Array.from(view.slice(0, 32));
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
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
window.__kbLastPos = null;

var _ii = WebAssembly.instantiate;
WebAssembly.instantiate = function(b, i) {
    // Wrap WASM import functions BEFORE instantiation
    if (i && typeof i === 'object') {
        Object.keys(i).forEach(function(mod) {
            var m = i[mod];
            if (m && typeof m === 'object') {
                Object.keys(m).forEach(function(fn) {
                    if (fn.indexOf('__wbg_send_') === 0 || fn.indexOf('__wbg_bufferData_') === 0 || fn.indexOf('__wbg_clientX') === 0 || fn.indexOf('__wbg_clientY') === 0 || fn.indexOf('__wbg_addEventListener_') === 0 || fn.indexOf('__wbg_drawArrays') === 0) {
                        var orig = m[fn];
                        m[fn] = function() {
                            try {
                                var info = {f:fn};
                                if ((fn.indexOf('send') >= 0 || fn.indexOf('bufferData') >= 0) && arguments.length > 0 && arguments[arguments.length-1] && arguments[arguments.length-1].byteLength) {
                                    var v = new Uint8Array(arguments[arguments.length-1]);
                                    info.d = Array.from(v.slice(0,32)).map(function(x){return x.toString(16).padStart(2,'0')}).join('');
                                } else if ((fn.indexOf('clientX') >= 0 || fn.indexOf('clientY') >= 0) && arguments.length > 0) {
                                    info.v = arguments[0];
                                }
                                console.log('KB_WM', JSON.stringify(info));
                            } catch(e) {}
                            return orig.apply(this, arguments);
                        };
                    }
                });
            }
        });
    }
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
        if (i && typeof i === 'object') {
            Object.keys(i).forEach(function(mod) {
                var m = i[mod];
                if (m && typeof m === 'object') {
                    Object.keys(m).forEach(function(fn) {
                        if (fn.indexOf('__wbg_send_') === 0 || fn.indexOf('__wbg_bufferData_') === 0 || fn.indexOf('__wbg_clientX') === 0 || fn.indexOf('__wbg_clientY') === 0 || fn.indexOf('__wbg_addEventListener_') === 0 || fn.indexOf('__wbg_drawArrays') === 0) {
                            var orig = m[fn];
                            m[fn] = function() {
                                try {
                                    var info = {f:fn};
                                    if ((fn.indexOf('send') >= 0 || fn.indexOf('bufferData') >= 0) && arguments.length > 0 && arguments[arguments.length-1] && arguments[arguments.length-1].byteLength) {
                                        var v = new Uint8Array(arguments[arguments.length-1]);
                                        info.d = Array.from(v.slice(0,32)).map(function(x){return x.toString(16).padStart(2,'0')}).join('');
                                    } else if ((fn.indexOf('clientX') >= 0 || fn.indexOf('clientY') >= 0) && arguments.length > 0) {
                                        info.v = arguments[0];
                                    }
                                    console.log('KB_WM', JSON.stringify(info));
                                } catch(e) {}
                                return orig.apply(this, arguments);
                            };
                        }
                    });
                }
            });
        }
        return _iis.call(this, s, i);
    };
}"
        }
"""

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
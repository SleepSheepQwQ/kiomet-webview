package com.kiomet.webview

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.webkit.*
import android.widget.*
import android.util.Log
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat

class MainActivity : AppCompatActivity() {
    private lateinit var webView: WebView
    private var bridgeServer: BridgeServer? = null
    private val handler = Handler(Looper.getMainLooper())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
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
        setupWebView(port)
        statusBadge.text = ":$port"
        statusBadge.visibility = View.VISIBLE

        refreshBtn.setOnClickListener { webView.reload() }

        settingsBtn.setOnClickListener {
            showPortDialog { newPort ->
                port = newPort
                prefs.edit().putInt("port", port).apply()
                bridgeServer?.stop()
                startBridge(port)
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
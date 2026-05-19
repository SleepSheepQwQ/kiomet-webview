package com.kiomet.webview

import android.os.Bundle
import android.webkit.*
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewClientCompat
import androidx.webkit.WebViewFeature

class MainActivity : AppCompatActivity() {
    private lateinit var webView: WebView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        webView = findViewById(R.id.webView)

        // 启动内嵌HTTP服务器
        BridgeServer.start(this)

        setupWebView()
        webView.loadUrl("https://kiomet.com")
    }

    private fun setupWebView() {
        val settings = webView.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.databaseEnabled = true
        settings.allowFileAccess = true
        settings.allowContentAccess = true
        settings.mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
        settings.cacheMode = WebSettings.LOAD_DEFAULT
        settings.userAgentString = settings.userAgentString + " KiometBridge/1.0"

        // 注入脚本
        if (WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
            WebViewCompat.addDocumentStartScript(
                webView,
                WebViewCompat.WEBVIEW_DOCUMENT_START_SCRIPT_ID,
                InjectedScript.CODE
            )
        } else {
            // Fallback: 用WebViewClient注入
            webView.webViewClient = object : WebViewClientCompat() {
                override fun onPageFinished(view: WebView, url: String) {
                    view.evaluateJavascript(InjectedScript.CODE, null)
                }
            }
        }

        // 捕获console.log输出到logcat
        webView.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(msg: ConsoleMessage): Boolean {
                android.util.Log.i("KB", "${msg.message()} (${msg.sourceId()}:${msg.lineNumber()})")
                return true
            }
        }
    }

    override fun onBackPressed() {
        if (webView.canGoBack()) webView.goBack() else super.onBackPressed()
    }

    override fun onDestroy() {
        BridgeServer.stop()
        super.onDestroy()
    }
}
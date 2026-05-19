package com.kiomet.webview

import android.util.Log
import java.io.*
import java.net.ServerSocket
import java.nio.charset.StandardCharsets.UTF_8
import java.util.concurrent.Executors
import kotlin.concurrent.thread

/**
 * 内嵌HTTP服务器（端口9999），接收WebView注入脚本捕获的数据
 */
object BridgeServer {
    private const val PORT = 9999
    private var serverSocket: ServerSocket? = null
    private var running = false

    fun start(context: android.content.Context) {
        if (running) return
        running = true
        thread(isDaemon = true) {
            try {
                serverSocket = ServerSocket(PORT)
                Log.i("KB", "BridgeServer listening on port $PORT")
                while (running) {
                    val client = serverSocket!!.accept()
                    Executors.newSingleThreadExecutor().submit { handle(client) }
                }
            } catch (e: Exception) {
                Log.e("KB", "BridgeServer error: ${e.message}")
            }
        }
    }

    fun stop() {
        running = false
        try { serverSocket?.close() } catch (_: Exception) {}
    }

    private fun handle(client: java.net.Socket) {
        try {
            client.use { sock ->
                val reader = BufferedReader(InputStreamReader(sock.getInputStream(), UTF_8))
                val writer = BufferedWriter(OutputStreamWriter(sock.getOutputStream(), UTF_8))

                // 读请求行
                val requestLine = reader.readLine() ?: return
                val parts = requestLine.split(" ")
                if (parts.size < 3) return
                val method = parts[0]
                val path = parts[1]

                // 读请求头
                val headers = mutableMapOf<String, String>()
                var line: String?
                var contentLength = 0
                while (reader.readLine().also { line = it } != null) {
                    if (line.isNullOrEmpty()) break
                    val colon = line.indexOf(':')
                    if (colon > 0) {
                        val key = line.substring(0, colon).trim().lowercase()
                        val value = line.substring(colon + 1).trim()
                        headers[key] = value
                        if (key == "content-length") contentLength = value.toIntOrNull() ?: 0
                    }
                }

                // 读body
                val body = if (contentLength > 0) {
                    val buf = CharArray(contentLength)
                    reader.read(buf, 0, contentLength)
                    String(buf)
                } else ""

                // 处理CORS
                if (method == "OPTIONS") {
                    respond(writer, 200, "OK", mapOf(
                        "Access-Control-Allow-Origin" to "*",
                        "Access-Control-Allow-Methods" to "GET, POST, OPTIONS",
                        "Access-Control-Allow-Headers" to "Content-Type",
                        "Access-Control-Max-Age" to "86400"
                    ))
                    return
                }

                when {
                    path == "/data" && method == "POST" -> {
                        Log.i("KB", "DATA: $body")
                        respond(writer, 200, """{"ok":true}""")
                    }
                    path == "/click" && method == "POST" -> {
                        Log.i("KB", "CLICK: $body")
                        respond(writer, 200, """{"ok":true}""")
                    }
                    method == "GET" -> {
                        respond(writer, 200, "Kiomet WebView Bridge", mapOf("Content-Type" to "text/plain"))
                    }
                    else -> respond(writer, 404, "Not Found")
                }
            }
        } catch (e: Exception) {
            Log.e("KB", "Handle error: ${e.message}")
        }
    }

    private fun respond(writer: BufferedWriter, status: Int, body: String, extraHeaders: Map<String, String>? = null) {
        val headers = mutableMapOf(
            "Content-Type" to "application/json; charset=utf-8",
            "Content-Length" to body.toByteArray(UTF_8).size.toString(),
            "Access-Control-Allow-Origin" to "*",
            "Connection" to "close"
        )
        extraHeaders?.forEach { (k, v) -> headers[k] = v }

        val statusText = when (status) { 200 -> "OK"; 404 -> "Not Found"; else -> "Error" }
        writer.write("HTTP/1.1 $status $statusText\r\n")
        headers.forEach { (k, v) -> writer.write("$k: $v\r\n") }
        writer.write("\r\n")
        writer.write(body)
        writer.flush()
    }
}
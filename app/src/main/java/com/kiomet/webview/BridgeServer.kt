package com.kiomet.webview

import android.util.Log
import java.io.*
import java.net.ServerSocket
import java.nio.charset.StandardCharsets.UTF_8
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.Executors

class BridgeServer(val port: Int) {
    private var serverSocket: ServerSocket? = null
    private var running = false
    private val messages = CopyOnWriteArrayList<String>()
    private val clicks = CopyOnWriteArrayList<String>()
    private val executor = Executors.newCachedThreadPool()

    fun start() {
        if (running) return
        running = true
        Thread { 
            try {
                serverSocket = ServerSocket(port)
                Log.i("KB", "Bridge listening on $port")
                while (running) {
                    val client = serverSocket!!.accept()
                    executor.submit { handle(client) }
                }
            } catch (e: Exception) {
                if (running) Log.e("KB", "Server error: ${e.message}")
            }
        }.start()
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

                val requestLine = reader.readLine() ?: return
                val parts = requestLine.split(" ")
                if (parts.size < 2) return
                val method = parts[0]
                val path = parts[1]

                var contentLength = 0
                var line: String?
                while (reader.readLine().also { line = it } != null) {
                    if (line.isNullOrEmpty()) break
                    val colon = line.indexOf(':')
                    if (colon > 0) {
                        val key = line.substring(0, colon).trim().lowercase()
                        val value = line.substring(colon + 1).trim()
                        if (key == "content-length") contentLength = value.toIntOrNull() ?: 0
                    }
                }

                val body = if (contentLength > 0) {
                    val buf = CharArray(contentLength)
                    reader.read(buf, 0, contentLength)
                    String(buf)
                } else ""

                if (method == "OPTIONS") {
                    respond(writer, 200, "OK")
                    return
                }

                when {
                    path == "/data" && method == "POST" -> {
                        messages.add(body)
                        Log.i("KB", "DATA: ${body.take(200)}")
                        respond(writer, 200, """{"ok":true}""")
                    }
                    path == "/click" && method == "POST" -> {
                        clicks.add(body)
                        Log.i("KB", "CLICK: $body")
                        respond(writer, 200, """{"ok":true}""")
                    }
                    path == "/data" && method == "GET" -> {
                        val json = messages.joinToString(",\n", "[\n", "\n]")
                        respond(writer, 200, json, "application/json")
                    }
                    path == "/clicks" && method == "GET" -> {
                        val json = clicks.joinToString(",\n", "[\n", "\n]")
                        respond(writer, 200, json, "application/json")
                    }
                    path == "/" && method == "GET" -> {
                        val html = """
                        <html><body>
                        <h2>Kiomet Bridge</h2>
                        <p>Port: $port</p>
                        <p>Messages: ${messages.size}</p>
                        <p>Clicks: ${clicks.size}</p>
                        <p><a href="/data">View Data</a></p>
                        <p><a href="/clicks">View Clicks</a></p>
                        </body></html>
                        """.trimIndent()
                        respond(writer, 200, html, "text/html")
                    }
                    else -> respond(writer, 404, "Not Found")
                }
            }
        } catch (e: Exception) {
            Log.e("KB", "Handle error: ${e.message}")
        }
    }

    private fun respond(w: BufferedWriter, status: Int, body: String, mime: String = "application/json") {
        val statusText = when (status) { 200 -> "OK"; 404 -> "Not Found"; else -> "Error" }
        w.write("HTTP/1.1 $status $statusText\r\n")
        w.write("Content-Type: $mime; charset=utf-8\r\n")
        w.write("Content-Length: ${body.toByteArray(UTF_8).size}\r\n")
        w.write("Access-Control-Allow-Origin: *\r\n")
        w.write("Connection: close\r\n\r\n")
        w.write(body)
        w.flush()
    }
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
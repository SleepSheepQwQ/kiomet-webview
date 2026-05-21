package com.kiomet.webview

import android.util.Log
import java.io.*
import java.net.ServerSocket
import java.nio.charset.StandardCharsets.UTF_8
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.Executors

class BridgeServer(val port: Int) {
    private var serverSocket: ServerSocket? = null
    @Volatile var running = false
    val messages = CopyOnWriteArrayList<String>()
    val clicks = CopyOnWriteArrayList<String>()
    private val executor = Executors.newCachedThreadPool()

    fun addMessage(json: String) { messages.add(json) }
    fun addClick(json: String) { clicks.add(json) }

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
                    path == "/log" && method == "POST" -> {
                        Log.i("KB", "LOG: $body")
                        respond(writer, 200, """{"ok":true}""")
                    }
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

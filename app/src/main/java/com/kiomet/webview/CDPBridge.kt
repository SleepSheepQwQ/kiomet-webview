package com.kiomet.webview

import android.net.LocalSocket
import android.net.LocalSocketAddress
import android.os.Process
import android.util.Log
import java.io.*
import java.net.ServerSocket
import java.net.Socket
import kotlin.concurrent.thread

// Based on unixshells/developer-tools (MIT)
class CDPBridge(private val port: Int = 9989) {
    companion object {
        private const val TAG = "CDPBridge"
        private const val BUFFER_SIZE = 65536
    }

    private var serverSocket: ServerSocket? = null
    @Volatile private var running = false

    fun start() {
        if (running) return
        running = true
        Log.i(TAG, "Starting CDP bridge on :$port")

        thread(name = "cdp-proxy", isDaemon = true) {
            try {
                val server = ServerSocket(port)
                serverSocket = server
                server.reuseAddress = true

                while (running) {
                    val client: Socket
                    try {
                        client = server.accept()
                    } catch (e: IOException) {
                        if (running) Log.e(TAG, "Accept failed: ${e.message}")
                        break
                    }
                    thread(name = "cdp-conn", isDaemon = true) {
                        val socketName = findSocketName()
                        if (socketName != null) {
                            handleConnection(client, socketName)
                        } else {
                            Log.e(TAG, "DevTools socket not found")
                            try { client.close() } catch (_: Exception) {}
                        }
                    }
                }
            } catch (e: Exception) {
                if (running) Log.e(TAG, "CDP proxy failed: ${e.message}")
            }
        }
    }

    private fun findSocketName(): String? {
        val pidName = "webview_devtools_remote_${Process.myPid()}"
        if (socketExists(pidName)) {
            Log.i(TAG, "Using PID-based socket: @$pidName")
            return pidName
        }
        try {
            val lines = File("/proc/net/unix").readLines()
            for (line in lines) {
                val idx = line.indexOf("@webview_devtools_remote_")
                if (idx >= 0) {
                    val name = line.substring(idx + 1)
                    Log.i(TAG, "Found socket via /proc/net/unix: @$name")
                    return name
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to scan /proc/net/unix: ${e.message}")
        }
        return null
    }

    private fun socketExists(name: String): Boolean {
        return try {
            val s = LocalSocket()
            s.connect(LocalSocketAddress(name, LocalSocketAddress.Namespace.ABSTRACT))
            s.close()
            true
        } catch (e: Exception) {
            false
        }
    }

    fun stop() {
        running = false
        try { serverSocket?.close() } catch (_: Exception) {}
        Log.i(TAG, "CDP bridge stopped")
    }

    private fun handleConnection(client: Socket, socketName: String) {
        var localSocket: LocalSocket? = null
        try {
            localSocket = LocalSocket()
            localSocket.connect(
                LocalSocketAddress(socketName, LocalSocketAddress.Namespace.ABSTRACT)
            )

            val clientIn = client.getInputStream()
            val clientOut = client.getOutputStream()
            val localIn = localSocket.inputStream
            val localOut = localSocket.outputStream

            // Read first chunk to check for WebSocket upgrade
            val firstChunk = ByteArray(BUFFER_SIZE)
            val firstLen = clientIn.read(firstChunk)
            if (firstLen == -1) return

            val firstData = String(firstChunk, 0, firstLen)
            val modifiedData = if (firstData.contains("Upgrade: websocket", ignoreCase = true) ||
                firstData.contains("upgrade: websocket", ignoreCase = true)) {
                // Strip Origin header - WebView DevTools rejects non-devtools origins
                val lines = firstData.split("\r\n").toMutableList()
                val filtered = lines.filter { line ->
                    !line.startsWith("Origin:", ignoreCase = true)
                }
                val result = filtered.joinToString("\r\n")
                Log.d(TAG, "Stripped Origin header from WebSocket upgrade")
                result
            } else {
                firstData
            }

            // Send the (possibly modified) first chunk to WebView
            localOut.write(modifiedData.toByteArray())
            localOut.flush()

            // Now pipe the rest bidirectionally
            val toLocal = thread(name = "cdp-to-local", isDaemon = true) {
                pipe(clientIn, localOut, "client->webview")
            }
            val toClient = thread(name = "cdp-to-client", isDaemon = true) {
                pipe(localIn, clientOut, "webview->client")
            }

            toLocal.join()
            toClient.join()

        } catch (e: Exception) {
            Log.e(TAG, "Connection error: ${e.message}")
        } finally {
            try { client.close() } catch (_: Exception) {}
            try { localSocket?.close() } catch (_: Exception) {}
        }
    }

    private fun pipe(input: InputStream, output: OutputStream, label: String) {
        val buffer = ByteArray(BUFFER_SIZE)
        try {
            while (true) {
                val read = input.read(buffer)
                if (read == -1) break
                output.write(buffer, 0, read)
                output.flush()
            }
        } catch (_: IOException) {
            // Connection closed
        }
        Log.d(TAG, "Pipe $label closed")
    }
}// v1.8 - import wrapping

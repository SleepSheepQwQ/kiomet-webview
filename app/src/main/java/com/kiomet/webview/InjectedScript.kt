package com.kiomet.webview

/**
 * 注入到WebView的JavaScript代码（document-start执行）
 * 无沙箱限制，可访问WASM内存、WebGL、WebSocket等
 */
object InjectedScript {
    val CODE = """
(function() {
    'use strict';
    // Test: verify script runs
    document.documentElement.style.border = '3px solid red';

    var BACKEND = 'http://127.0.0.1:9999';

    // ===== Logging =====
    function log(msg) {
        console.log('[KB]', msg);
        try {
            var x = new XMLHttpRequest();
            x.open('POST', BACKEND + '/log', true);
            x.setRequestHeader('Content-Type', 'text/plain');
            x.send(msg);
        } catch(e) {}
    }

    // ===== WebSocket hook (捕获所有收发数据) =====
    var OrigWS = window.WebSocket;
    window.WebSocket = function(url, protocols) {
        var ws = new OrigWS(url, protocols);
        if (typeof url !== 'string' || url.indexOf('kiomet') === -1) return ws;
        log('WS: ' + url);

        // Hook instance send
        var origSend = ws.send.bind(ws);
        ws.send = function(data) {
            var info = { dir: 'out', size: data.byteLength || data.length || 0, time: Date.now() };
            if (data instanceof ArrayBuffer) {
                info.hex = Array.from(new Uint8Array(data)).map(function(b) { return ('0' + b.toString(16)).slice(-2); }).join('');
            } else if (ArrayBuffer.isView(data)) {
                info.hex = Array.from(new Uint8Array(data.buffer, data.byteOffset, data.byteLength)).map(function(b) { return ('0' + b.toString(16)).slice(-2); }).join('');
            }
            sendToBridge('data', info);
            return origSend(data);
        };

        // Hook message
        ws.addEventListener('message', function(e) {
            if (e.data instanceof ArrayBuffer) {
                var u8 = new Uint8Array(e.data);
                sendToBridge('data', { dir: 'in', size: u8.length, hex: Array.from(u8.slice(0,64)).map(function(b) { return ('0' + b.toString(16)).slice(-2); }).join(''), time: Date.now() });
            }
        });
        return ws;
    };
    window.WebSocket.prototype = OrigWS.prototype;

    // Prototype send hook (catches sends from WASM-initiated WebSockets)
    if (!OrigWS.prototype.__kbHooked) {
        OrigWS.prototype.__kbHooked = true;
        var origProtoSend = OrigWS.prototype.send;
        OrigWS.prototype.send = function(data) {
            var info = { dir: 'out', size: data.byteLength || data.length || 0, time: Date.now() };
            if (data instanceof ArrayBuffer) {
                info.hex = Array.from(new Uint8Array(data)).map(function(b) { return ('0' + b.toString(16)).slice(-2); }).join('');
            } else if (ArrayBuffer.isView(data)) {
                info.hex = Array.from(new Uint8Array(data.buffer, data.byteOffset, data.byteLength)).map(function(b) { return ('0' + b.toString(16)).slice(-2); }).join('');
            }
            sendToBridge('data', info);
            return origProtoSend.call(this, data);
        };
    }

    // ===== Camera matrix capture (WebGL) =====
    var cameraMatrix = null;
    function hookWebGL() {
        try {
            var proto = WebGL2RenderingContext && WebGL2RenderingContext.prototype || WebGLRenderingContext && WebGLRenderingContext.prototype;
            if (!proto) return;
            var orig = proto.uniformMatrix3fv;
            if (!orig) return;
            proto.uniformMatrix3fv = function(loc, trans, data) {
                if (data && data.length === 9) cameraMatrix = Array.from(data);
                return orig.call(this, loc, trans, data);
            };
            log('WebGL hooked');
        } catch(e) { log('WebGL err: ' + e.message); }
    }

    // ===== WASM instance capture =====
    var wasmInstance = null;
    function hookWASM() {
        var origInstantiate = WebAssembly.instantiate;
        WebAssembly.instantiate = function(module, imports) {
            return origInstantiate.call(WebAssembly, module, imports).then(function(inst) {
                wasmInstance = inst;
                log('WASM captured: ' + (inst.exports.memory ? inst.exports.memory.buffer.byteLength + ' bytes' : 'no memory'));
                return inst;
            });
        };
        log('WASM hook installed');
    }

    // ===== Canvas click → TowerId =====
    function hookClicks() {
        var check = function() {
            var canvas = document.getElementById('canvas') || document.querySelector('canvas');
            if (!canvas) { setTimeout(check, 1000); return; }
            canvas.addEventListener('touchend', function(e) {
                var t = e.changedTouches[0];
                if (!t) return;
                var r = canvas.getBoundingClientRect();
                var sx = t.clientX - r.left, sy = t.clientY - r.top;
                var result = { screenX: sx, screenY: sy, canvasW: canvas.width, canvasH: canvas.height, time: Date.now() };
                if (cameraMatrix) {
                    var m = cameraMatrix;
                    var ndx = sx / canvas.width * 2 - 1, ndy = -(sy / canvas.height * 2 - 1);
                    var tx = Math.floor((ndx * 5 - m[2]) / m[0]), ty = Math.floor((ndy * 5 - m[5]) / m[4]);
                    result.towerId = { x: tx, y: ty };
                }
                sendToBridge('click', result);
            });
            log('Canvas hooked');
        };
        check();
    }

    // ===== Bridge API (native JS bridge preferred, then HTTP fallback) =====
    function sendToBridge(type, data) {
        var json = JSON.stringify(data);
        // Native bridge (no CORS issues, always available)
        if (window.KB && window.KB.send) {
            try { window.KB.send(type, json); return; } catch(e) {}
        }
        // HTTP fallback
        try {
            var x = new XMLHttpRequest();
            x.open('POST', BACKEND + '/' + type, true);
            x.setRequestHeader('Content-Type', 'application/json');
            x.send(json);
        } catch(e) {
            try { navigator.sendBeacon(BACKEND + '/' + type, json); } catch(e2) {}
        }
    }

    // ===== Init =====
    hookWASM();
    hookWebGL();
    hookClicks();
    log('Bridge injected');
})();
"""
}
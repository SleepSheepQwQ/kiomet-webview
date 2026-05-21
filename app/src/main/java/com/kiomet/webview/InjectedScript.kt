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
    
    // Prototype send hook: 用Object.defineProperty绕过非writable限制
    try {
        var _origProtoSend = OrigWS.prototype.send;
        Object.defineProperty(OrigWS.prototype, 'send', {
            configurable: true,
            enumerable: true,
            writable: true,
            value: function(data) {
                var info = { dir: 'out', size: data.byteLength || data.length || 0, time: Date.now() };
                try {
                    if (data instanceof ArrayBuffer) {
                        info.hex = Array.from(new Uint8Array(data)).map(function(b) { return ('0' + b.toString(16)).slice(-2); }).join('');
                    } else if (ArrayBuffer.isView(data)) {
                        info.hex = Array.from(new Uint8Array(data.buffer, data.byteOffset, data.byteLength)).map(function(b) { return ('0' + b.toString(16)).slice(-2); }).join('');
                    }
                } catch(e) {}
                sendToBridge('data', info);
                return _origProtoSend.call(this, data);
            }
        });
    } catch(e) { log('send proto hook err: ' + (e.message||'')); }

    // Constructor hook (用于message监听和实例send覆盖)
    window.WebSocket = function(url, protocols) {
        var ws = new OrigWS(url, protocols);
        if (typeof url !== 'string' || url.indexOf('kiomet') === -1) return ws;
        log('WS: ' + url);

        // 实例send覆盖（作为prototype hook的备用）
        try {
            var origSend = ws.send.bind(ws);
            ws.send = function(data) {
                origSend(data);
            };
        } catch(e) {}

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

    // ===== Camera matrix capture (WebGL) =====
    var cameraMatrix = null;
    function hookWebGL() {
        try {
            var proto = WebGL2RenderingContext && WebGL2RenderingContext.prototype || WebGLRenderingContext && WebGLRenderingContext.prototype;
            if (!proto) return;
            var orig = proto.uniformMatrix3fv;
            if (!orig) return;
            window.__kbCameraHooked = true;
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
        function check() {
            var canvas = document.getElementById('canvas') || document.querySelector('canvas');
            if (!canvas) { setTimeout(check, 500); return; }
            window.__kbCanvasHooked = true;
            
            function handler(e) {
                e.stopPropagation();
                var t = e.changedTouches ? e.changedTouches[0] : null;
                if (!t) t = e;
                var r = canvas.getBoundingClientRect();
                var sx = (t.clientX || 0) - r.left, sy = (t.clientY || 0) - r.top;
                var result = { screenX: sx, screenY: sy, canvasW: canvas.width, canvasH: canvas.height, time: Date.now() };
                if (cameraMatrix) {
                    var m = cameraMatrix;
                    var ndx = sx / canvas.width * 2 - 1, ndy = -(sy / canvas.height * 2 - 1);
                    var tx = Math.floor((ndx * 5 - m[2]) / m[0]), ty = Math.floor((ndy * 5 - m[5]) / m[4]);
                    result.towerId = { x: tx, y: ty };
                }
                sendToBridge('click', result);
            }
            
            // 使用capture阶段监听，优先于游戏自身的处理
            canvas.addEventListener('pointerdown', handler, { capture: true, passive: true });
            canvas.addEventListener('touchend', handler, { capture: true, passive: true });
            canvas.addEventListener('click', handler, { capture: true, passive: true });
        }
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
    // Keep retrying hooks periodically (canvas might be created later)
    setInterval(function() {
        if (!window.__kbCanvasHooked) hookClicks();
        if (!window.__kbCameraHooked) hookWebGL();
    }, 2000);
    log('Bridge injected');
})();
"""
}
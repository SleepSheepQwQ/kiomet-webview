#!/usr/bin/env python3
"""Read tower positions from WASM memory via CDP."""
import asyncio, json, http.client, os, struct, sys

CDP_PORT = 9989

MEM_SCAN = """
(function() {
    var mem = window.__kbMem;
    var exp = window.__kbExp;
    if (!mem) return JSON.stringify({error: 'no memory - reload page'});
    
    var buf = new Uint8Array(mem.buffer);
    var results = [];
    
    // Scan for Option<Tower> patterns
    // Tower struct: [pid:u16][type:u8][delay:u8][x:u16][y:u16][units:u32]
    // Option tag: 0 = None, 1 = Some
    // In Chunk layout: Box<[Option<Tower>; 256]>
    // Each entry: tag(1) + Tower(12) = 13 bytes
    // 256 entries * 13 = 3328 bytes per Chunk
    
    // Known player ID from the user's towers
    // Scan for u16 values matching known tower positions
    
    var knownPlayerId = null;
    var towers = [];
    
    // Search for patterns: u16 x u16 y pairs where y follows x
    for (var offset = 0; offset < buf.length - 16; offset += 2) {
        var tag = buf[offset];
        if (tag !== 0 && tag !== 1) continue;
        
        var pid = buf[offset+1] | (buf[offset+2] << 8);
        var type = buf[offset+3];
        var delay = buf[offset+4];
        var tx = buf[offset+5] | (buf[offset+6] << 8);
        var ty = buf[offset+7] | (buf[offset+8] << 8);
        var units = buf[offset+9] | (buf[offset+10] << 8) | (buf[offset+11] << 16) | (buf[offset+12] << 24);
        
        // Validate: tower type 0-26, coordinates in reasonable range
        if (type <= 26 && tx > 0 && tx < 65535 && ty > 0 && ty < 65535 && units < 100000) {
            if (knownPlayerId === null) knownPlayerId = pid;
            towers.push({tag:tag, pid:pid, type:type, x:tx, y:ty, units:units, offset:offset});
        }
    }
    
    return JSON.stringify({playerId: knownPlayerId, count: towers.length, towers: towers.slice(0, 50)});
})();
"""

async def main():
    conn = http.client.HTTPConnection("127.0.0.1", CDP_PORT, timeout=5)
    conn.request("GET", "/json")
    t = json.loads(conn.getresponse().read())
    conn.close()
    if not t: print("No CDP target"); return
    ws_url = t[0]["webSocketDebuggerUrl"]
    ws_url = ws_url.replace("ws://localhost", f"ws://127.0.0.1:{CDP_PORT}")
    
    import websockets
    async with websockets.connect(ws_url, max_size=2**24) as ws:
        await ws.send(json.dumps({"id":1,"method":"Runtime.enable"}))
        await ws.recv()
        
        await ws.send(json.dumps({"id":2,"method":"Runtime.evaluate","params":{"expression":MEM_SCAN}}))
        
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(raw)
            if msg.get("id") == 2:
                val = msg.get("result",{}).get("result",{}).get("value","{}")
                data = json.loads(val)
                if data.get("error"):
                    print(f"Error: {data['error']}")
                else:
                    print(f"Player ID: {data.get('playerId')}")
                    print(f"Towers found: {data.get('count')}")
                    for tw in data.get("towers", []):
                        type_names = ["Mine","Barracks","Armory","Cliff","Quarry","Silo","Rampart",
                            "Factory","Centrifuge","Projector","Refinery","Generator","Reactor",
                            "Bunker","Artillery","Radar","EWS","Satellite","Rocket","Runway",
                            "Airfield","Helipad","Village","HQ","Town","City","Fortress"]
                        tname = type_names[tw['type']] if tw['type'] < len(type_names) else f"T{tw['type']}"
                        owner = "YOU" if tw['pid'] == data.get('playerId') else f"P{tw['pid']}"
                        print(f"  [{owner}] {tname} at ({tw['x']},{tw['y']}) units={tw['units']}")
                break

asyncio.run(main())
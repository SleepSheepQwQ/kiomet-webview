
"""CDP script for v1.15: read tower positions + raw ws data + WASM call log."""
import socket, time, json, os, base64, sys, struct

def get_ws():
    import urllib.request
    resp = json.loads(urllib.request.urlopen("http://127.0.0.1:9989/json", timeout=5).read())
    return next(p["webSocketDebuggerUrl"] for p in resp if "kiomet.com" in p.get("url",""))

s = socket.socket(); s.settimeout(15)
s.connect(("127.0.0.1", 9989))
path = get_ws().replace("ws://127.0.0.1:9989", "")
key = base64.b64encode(os.urandom(16)).decode()
s.send(f"GET {path} HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
time.sleep(1); s.recv(4096)

def send(mid, method, params=None):
    p = {"id": mid, "method": method}
    if params: p["params"] = params
    data = json.dumps(p).encode(); mask = os.urandom(4); md = bytearray(len(data))
    for i in range(len(data)): md[i] = data[i] ^ mask[i & 3]
    f = bytearray([0x81]); L = len(data)
    if L < 126: f.append(0x80 | L)
    elif L < 65536: f.append(0x80 | 126); f.extend(L.to_bytes(2, "big"))
    else: f.append(0x80 | 127); f.extend(L.to_bytes(8, "big"))
    f += bytearray(mask) + bytearray(md); s.send(bytes(f))

def recv(timeout=2):
    s.settimeout(timeout); frames = []
    try:
        while True:
            b1 = s.recv(1); oc = b1[0]&0x0f; b2 = s.recv(1)[0]; L = b2&0x7f
            if L==126: L=int.from_bytes(s.recv(2),"big")
            elif L==127: L=int.from_bytes(s.recv(8),"big")
            if oc==0x8: break
            if oc==0x9: s.send(bytes([0x8a,0x00])); continue
            frames.append(json.loads(s.recv(L).decode()))
    except: pass
    return frames

def js(mid, expr):
    send(mid, "Runtime.evaluate", {"expression": expr, "returnByValue": True})
    time.sleep(0.5)
    for r in recv():
        if "result" in r and "result" in r["result"]:
            return r["result"]["result"].get("value")

# Tower type names (from game source TowerType enum, index = discriminant)
TOWER_TYPES = [
    "Airfield", "Armory", "Artillery", "Barracks", "Bunker",
    "Centrifuge", "City", "Cliff", "Ews", "Factory",
    "Generator", "Headquarters", "Helipad", "Launcher", "Mine",
    "Projector", "Quarry", "Radar", "Rampart", "Reactor",
    "Refinery", "Rocket", "Runway", "Satellite", "Silo",
    "Town", "Village"
]

FACTION_MAP = {1: "Blue(Player)", 2: "Purple(Ally)", 3: "Red(Enemy)"}
def faction_name(color_id):
    if color_id == 1: return "Blue(Player)"
    if 2 <= color_id <= 127: return "Purple(Ally)"
    if color_id >= 128: return "Red(Enemy)"
    return "Neutral"

send(1, "Runtime.enable"); time.sleep(0.3); recv()

# 1. Read tower positions (coordinates + faction from texture)
pos = js(2, "JSON.stringify(window.__kbTowerPositions)")
print("=== TOWER POSITIONS ===", flush=True)
if pos and pos not in ("[]", "null"):
    towers = json.loads(pos)
    print(f"Found {len(towers)} towers", flush=True)
    for t in towers:
        print(f"  ({t['s'][0]}, {t['s'][1]}) screen | grid ({t['w'][0]}, {t['w'][1]}) | faction={faction_name(t['id'])} color_id={t['id']}", flush=True)
else:
    print("No towers found", flush=True)

# 1b. Run WASM memory scanner to get tower types
mem_result = js(5, "JSON.stringify(window.__kbScanMemoryForTypes ? __kbScanMemoryForTypes() : null)")
print("\n=== WASM MEMORY SCAN (tower types) ===", flush=True)
if mem_result and mem_result not in ("[]", "null"):
    mem_towers = json.loads(mem_result)
    found = [t for t in mem_towers if t["type"] >= 0]
    print(f"Scanned {len(mem_towers)} towers, {len(found)} had type info", flush=True)
    for t in found:
        tname = TOWER_TYPES[t["type"]] if t["type"] < len(TOWER_TYPES) else "???"
        print(f"  grid({t['w'][0]},{t['w'][1]}) screen({t['s'][0]},{t['s'][1]}) type={t['type']}({tname}) offset=0x{t['offset']:x}", flush=True)
else:
    print("Memory scan returned no results (memory not available or tower data not in expected format)", flush=True)
    # Also try reading __kbTowerPositionsWithTypes if already populated
    wt = js(5, "JSON.stringify(window.__kbTowerPositionsWithTypes || null)")
    if wt and wt not in ("[]", "null"):
        wt_data = json.loads(wt)
        found = [t for t in wt_data if t["type"] >= 0]
        print(f"  Found {len(found)} tower types from __kbTowerPositionsWithTypes", flush=True)
raw_msg = js(3, "JSON.stringify(window.__kbRawMessages)")
print("\n=== RAW WS MESSAGES ===", flush=True)
if raw_msg and raw_msg not in ("[]", "null"):
    msgs = json.loads(raw_msg)
    print(f"Captured {len(msgs)} messages", flush=True)
    for i, m in enumerate(msgs):
        raw = bytes.fromhex(m["d"])
        print(f"  msg[{i}]: {m['n']} bytes (shown: {len(raw)}) hex={raw[:32].hex()}...", flush=True)

        # Try to decode the bitcode Update message
        # Structure: actor_update (unknown) + non_actor
        # non_actor: alive(u8) + alerts + tower_counts(27*u16) + death_reason + bounding_rect
        # Scan for the alive marker (0x00 or 0x01) near expected offset
        if len(raw) > 16:
            for offset in range(0, min(len(raw) - 60, 200)):
                if raw[offset] in (0, 1) and offset > 4:
                    after_alive = offset + 1
                    # alerts comes next - variable size. Try skipping ~8-16 bytes for alerts
                    for alert_skip in range(4, 24):
                        twr_start = after_alive + alert_skip
                        if twr_start + 54 <= len(raw):
                            tower_counts_raw = raw[twr_start:twr_start+54]
                            # TowerArray<u16> has 27 entries. Check if they're plausible (0-10000)
                            counts = struct.unpack_from("<" + "H" * 27, tower_counts_raw)
                            max_count = max(counts)
                            if 0 < max_count < 10000:
                                print(f"    bitcode decode found at offset {offset} (alive=0x{raw[offset]:02x}), tower_counts at {twr_start}", flush=True)
                                total = sum(counts)
                                print(f"    total towers from counts: {total}", flush=True)
                                break
                    break

        # Try to find tower types from raw bytes
        # TowerType is u8 enum (0-26)
        # TowerId is (u16, u16) - grid coordinates
        # After a ws message, the WASM processes it and stores tower data
        # The raw bytes contain tower positions + types in bitcode columnar format
        print(f"    looking for tower data patterns...", flush=True)

        # Scan for u16 pairs that look like tower grid positions
        if len(raw) > 10:
            found = 0
            for off in range(0, len(raw) - 4):
                x = struct.unpack_from("<H", raw, off)[0]
                y = struct.unpack_from("<H", raw, off+2)[0]
                if 0 <= x < 512 and 0 <= y < 512 and (x > 0 or y > 0):
                    # These look like grid coordinates - check nearby bytes for type
                    type_candidates = set()
                    for toff in range(max(0, off-5), min(len(raw)-1, off+5)):
                        v = raw[toff]
                        if 0 <= v < 27 and v not in (0, 16, 24, 25, 26):  # plausible tower type
                            type_candidates.add(v)
                    if type_candidates:
                        pass  # will report with positions
                    found += 1
                    if found >= 8:
                        break
else:
    print("No raw messages captured", flush=True)

# 3. Read WASM call explorer log
call_log = js(4, "JSON.stringify(window.__kbCallLog)")
print("\n=== WASM CALL EXPLORER ===", flush=True)
if call_log and call_log not in ("[]", "null"):
    calls = json.loads(call_log)
    print(f"Captured {len(calls)} calls", flush=True)

    # Group by function name
    from collections import Counter
    fn_counts = Counter()
    for c in calls:
        fn_counts[c["n"]] += 1

    print("\nTop 30 most called functions:", flush=True)
    for fn, count in fn_counts.most_common(30):
        print(f"  {fn}: {count}x", flush=True)

    # Look for functions with u8 args in tower type range (0-26)
    print("\nFunctions with small integer args (potential tower type):", flush=True)
    type_fns = {}
    for c in calls:
        if "v0" in c and isinstance(c["v0"], (int, float)):
            v = int(c["v0"])
            if 0 <= v < 27:
                fn = c["n"]
                if fn not in type_fns:
                    type_fns[fn] = {"types": set(), "count": 0}
                type_fns[fn]["types"].add(v)
                type_fns[fn]["count"] += 1

    for fn, info in sorted(type_fns.items(), key=lambda x: -x[1]["count"])[:15]:
        types_str = ", ".join(f"{t}({TOWER_TYPES[t]})" for t in sorted(info["types"]) if t < len(TOWER_TYPES))
        print(f"  {fn}: {info['count']}x, types={types_str}", flush=True)

    # Print sample calls for most frequent unknown functions
    print("\nSample calls (first 15):", flush=True)
    for c in calls[:15]:
        vstr = f"v0={c.get('v0')}" if "v0" in c else f"d0={c.get('d0','')[:32]}"
        print(f"  {c['n']}: {vstr}", flush=True)

    # Recommend which functions to add to isRender filter
    print("\n== RECOMMENDATION ==", flush=True)
    for fn, info in sorted(type_fns.items(), key=lambda x: -x[1]["count"])[:5]:
        types_str = ", ".join(TOWER_TYPES[t] for t in sorted(info["types"]) if t < len(TOWER_TYPES))
        print(f"  Add '{fn}' to isRender filter for tower type capture (types: {types_str})", flush=True)
else:
    print("No call log captured (call count was 0 - WASM may not have instantiated yet)", flush=True)

# 4. Try to click on first tower if found
if pos and pos not in ("[]", "null"):
    try:
        towers = json.loads(pos)
        if towers and len(towers) > 0:
            for t in towers[:3]:
                sx, sy = t["s"]
                print(f"\nClicking tower at ({sx}, {sy})", flush=True)
                send(10, "Input.dispatchMouseEvent", {"type":"mousePressed","x":sx,"y":sy,"button":"left","clickCount":1})
                time.sleep(0.1)
                send(11, "Input.dispatchMouseEvent", {"type":"mouseReleased","x":sx,"y":sy,"button":"left","clickCount":1})
                time.sleep(1)
    except Exception as e:
        print(f"Click error: {e}", flush=True)

s.close()

import time
import board
import busio
import rotaryio
import usb_hid
import socketpool
import wifi
import adafruit_ssd1306
from digitalio import DigitalInOut, Direction, Pull
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keycode import Keycode
from adafruit_hid.consumer_control import ConsumerControl
from adafruit_hid.consumer_control_code import ConsumerControlCode

# ------------- HARDWARE SETUP -------------
i2c = busio.I2C(board.GP1, board.GP0, frequency=400000)
oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c)
kbd = Keyboard(usb_hid.devices)
cc = ConsumerControl(usb_hid.devices)
encoder = rotaryio.IncrementalEncoder(board.GP14, board.GP15)

# Key matrix
row_pins = [board.GP2, board.GP3, board.GP4, board.GP5]
col_pins = [board.GP6, board.GP7, board.GP8, board.GP9]
rows = [DigitalInOut(p) for p in row_pins]
for r in rows:
    r.direction = Direction.OUTPUT
    r.value = True
cols = [DigitalInOut(p) for p in col_pins]
for c in cols:
    c.direction = Direction.INPUT
    c.pull = Pull.UP

# ------------- WI-FI CONFIG -------------
WIFI_SSID = "MANI"
WIFI_PASS = "homies2659"
WIFI_PORT = 80

# Global Wi‑Fi objects
pool = None
server_sock = None
client_sock = None
device_ip = "No WiFi"

# Connection cooldown (seconds between reconnect attempts)
reconnect_cooldown = 30
last_reconnect_try = 0

def init_wifi():
    """Non‑blocking attempt. Returns True if connected."""
    global pool, server_sock, device_ip, last_reconnect_try
    if wifi.radio.connected:
        return True
    now = time.monotonic()
    if now - last_reconnect_try < reconnect_cooldown:
        return False
    last_reconnect_try = now
    try:
        # timeout prevents infinite hang
        wifi.radio.connect(WIFI_SSID, WIFI_PASS, timeout=10)
        device_ip = str(wifi.radio.ipv4_address)
        pool = socketpool.SocketPool(wifi.radio)
        server_sock = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
        server_sock.setsockopt(pool.SOL_SOCKET, pool.SO_REUSEADDR, 1)
        server_sock.setblocking(False)
        server_sock.bind(("", WIFI_PORT))
        server_sock.listen(1)
        print(f"Connected. IP: {device_ip}")
        return True
    except Exception as e:
        print(f"WiFi connect failed: {e}")
        device_ip = "No WiFi"
        pool = None
        server_sock = None
        return False

# Attempt first connection (may block up to 10 s, acceptable at startup)
init_wifi()

# ------------- STATE VARIABLES -------------
last_position = encoder.position
volume_level = 50
last_action = "READY"
display_dirty = True
last_display_time = 0
current_mode = 0           # 0=Volume, 1=Scroll
screen_on = True
last_input_time = time.monotonic()
SLEEP_DELAY = 30

scroll_key_held = None
scroll_hold_time = 0
SCROLL_HOLD_DURATION = 0.2

# ------------- KEY MAPPING (row, col) -------------
KEY_NEXT_TRACK      = (1, 1)
KEY_PREV_TRACK      = (1, 2)
KEY_PLAY_PAUSE      = (1, 3)
KEY_MUTE            = (1, 4)

KEY_WORKPLACE_RIGHT = (2, 1)
KEY_QUIT_APP        = (2, 2)
KEY_DICTATION       = (2, 3)
KEY_MODE_TOGGLE     = (2, 4)

KEY_SCREENSHOT      = (3, 1)
KEY_COPY            = (3, 2)
KEY_PASTE           = (3, 3)
KEY_UNDO            = (3, 4)

KEY_SWITCH_TABS     = (4, 1)
KEY_ZOOM_IN         = (4, 2)
KEY_ZOOM_OUT        = (4, 3)
KEY_DESKTOP         = (4, 4)

# ------------- COMPACT WEB PAGE (in chunks) -------------
# Split the page into small chunks to send non‑blockingly.
page_chunks = [
    b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n"
    b"<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>"
    b"<style>body{background:#000;color:#fff;font-family:system-ui;padding:8px;max-width:400px;margin:0 auto}"
    b"header{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}"
    b".logo{font-weight:800;letter-spacing:2px;font-size:.8rem}"
    b".ip{font-size:.6rem;color:#555}"
    b"#status-bar{background:#111;border:1px solid #222;border-radius:6px;padding:6px;margin-bottom:6px;display:flex;gap:6px}"
    b"#status{font-weight:700;flex:1}"
    b".vol-wrap{display:flex;align-items:center;gap:4px}"
    b".vol-track{width:60px;background:#222;height:4px;border-radius:2px}"
    b".vol-fill{height:4px;background:#4ade80;border-radius:2px}"
    b".vol-num{font-size:.6rem;color:#888;min-width:24px;text-align:right}"
    b".grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:3px;margin-bottom:4px}"
    b"btn{display:block;background:#141414;color:#aaa;border:1px solid #333;border-radius:4px;padding:10px 2px;font-size:.6rem;font-weight:700;text-align:center;cursor:pointer;user-select:none}"
    b"btn:active{background:#252525;border-color:#555}"
    b".g{border-color:#4ade8044;color:#4ade80}.r{border-color:#f8717144;color:#f87171}"
    b".b{border-color:#60a5fa44;color:#60a5fa}.y{border-color:#fbbf2444;color:#fbbf24}"
    b".p{border-color:#c084fc44;color:#c084fc}"
    b"</style></head><body>",
    # IP address placeholder – inserted separately
    b"<header><div class='logo'>&#9632; MacroPad</div><div class='ip'>",
    b"",  # IP string will be put here
    b"</div></header>"
    b"<div id='status-bar'><div id='status'>READY</div>"
    b"<div class='vol-wrap'><div class='vol-track'><div class='vol-fill' id='vbar' style='width:50%'></div></div>"
    b"<div class='vol-num' id='vlabel'>50%</div></div></div>"
    b"<div class='grid4'>"
    b"<btn class='b' onclick=\"cmd('NEXT_TRACK')\">&#9654;&#9654;</btn>"
    b"<btn class='b' onclick=\"cmd('PREV_TRACK')\">&#9664;&#9664;</btn>"
    b"<btn class='g' onclick=\"cmd('PLAY_PAUSE')\">&#9654;</btn>"
    b"<btn class='r' onclick=\"cmd('MUTE')\">MUTE</btn>"
    b"<btn class='b' onclick=\"cmd('WORKPLACE_RIGHT')\">&#8594;</btn>"
    b"<btn class='r' onclick=\"cmd('QUIT_APP')\">QUIT</btn>"
    b"<btn class='y' onclick=\"cmd('DICTATION')\">DICT</btn>"
    b"<btn class='p' onclick=\"cmd('MODE_TOGGLE')\">MODE</btn>"
    b"<btn class='y' onclick=\"cmd('SCREENSHOT')\">SNIP</btn>"
    b"<btn onclick=\"cmd('COPY')\">COPY</btn>"
    b"<btn onclick=\"cmd('PASTE')\">PASTE</btn>"
    b"<btn onclick=\"cmd('UNDO')\">UNDO</btn>"
    b"<btn class='b' onclick=\"cmd('SWITCH_TABS')\">TABS</btn>"
    b"<btn class='g' onclick=\"cmd('ZOOM_IN')\">+</btn>"
    b"<btn class='r' onclick=\"cmd('ZOOM_OUT')\">-</btn>"
    b"<btn class='y' onclick=\"cmd('DESKTOP')\">DSK</btn>"
    b"<btn class='g' onclick=\"cmd('VOLUP')\">&#9650;</btn>"
    b"<btn class='r' onclick=\"cmd('VOLDN')\">&#9660;</btn>"
    b"</div>"
    b"<script>function cmd(a){fetch('/cmd?action='+a)}"
    b"setInterval(()=>{fetch('/status').then(r=>r.json()).then(d=>{"
    b"document.getElementById('status').textContent=d.action;"
    b"document.getElementById('vbar').style.width=d.vol+'%';"
    b"document.getElementById('vlabel').textContent=d.vol+'%'})},500)</script></body></html>"
]

# For non‑blocking send, we keep track of which chunk we are sending.
send_state = {
    "client": None,
    "chunks": [],
    "chunk_idx": 0,
    "ip_sent": False
}

# ------------- NON‑BLOCKING SEND HELPER -------------
def try_send_all(client, data):
    """Send data non‑blockingly. Returns True when done, False if would block."""
    try:
        # data can be bytearray or bytes; send may still block on full buffer
        client.send(data)
        return True
    except OSError as e:
        if e.errno == 11:  # EAGAIN
            return False
        raise

# ------------- UNIFIED ACTION EXECUTOR -------------
def execute_action(action):
    global volume_level, last_action, current_mode, display_dirty
    action = action.strip().upper()

    # Media
    if action in ("PLAY_PAUSE", "PLAY"):
        cc.send(ConsumerControlCode.PLAY_PAUSE)
        last_action = "PLAY/PAUSE"
    elif action in ("PREV_TRACK", "PREV"):
        cc.send(ConsumerControlCode.SCAN_PREVIOUS_TRACK)
        last_action = "PREV TRACK"
    elif action in ("NEXT_TRACK", "NEXT"):
        cc.send(ConsumerControlCode.SCAN_NEXT_TRACK)
        last_action = "NEXT TRACK"
    elif action == "MUTE":
        cc.send(ConsumerControlCode.MUTE)
        last_action = "MUTE"
    # Volume
    elif action == "VOLUP":
        cc.send(ConsumerControlCode.VOLUME_INCREMENT)
        volume_level = min(100, volume_level + 2)
        last_action = "VOL +2"
    elif action == "VOLDN":
        cc.send(ConsumerControlCode.VOLUME_DECREMENT)
        volume_level = max(0, volume_level - 2)
        last_action = "VOL -2"
    # App
    elif action in ("WORKPLACE_RIGHT", "WORKPLACE"):
        kbd.send(Keycode.CONTROL, Keycode.RIGHT_ARROW)
        last_action = "WORKPLACE →"
    elif action in ("QUIT_APP", "QUIT"):
        kbd.press(Keycode.GUI, Keycode.Q)
        time.sleep(0.05)
        kbd.release_all()
        last_action = "QUIT APP"
    elif action in ("DICTATION", "DICTATE"):
        kbd.press(Keycode.CONTROL)
        kbd.release(Keycode.CONTROL)
        time.sleep(0.03)
        kbd.press(Keycode.CONTROL)
        kbd.release(Keycode.CONTROL)
        last_action = "DICTATION"
    elif action in ("MODE_TOGGLE", "MODE"):
        current_mode = (current_mode + 1) % 2
        last_action = "MODE: VOL" if current_mode == 0 else "MODE: SCRL"
    # Edit
    elif action in ("SCREENSHOT", "SNIP"):
        kbd.send(Keycode.GUI, Keycode.SHIFT, Keycode.FOUR)
        last_action = "SCREENSHOT"
    elif action == "COPY":
        kbd.send(Keycode.GUI, Keycode.C)
        last_action = "COPY"
    elif action == "PASTE":
        kbd.send(Keycode.GUI, Keycode.V)
        last_action = "PASTE"
    elif action == "UNDO":
        kbd.send(Keycode.GUI, Keycode.Z)
        last_action = "UNDO"
    # System
    elif action in ("SWITCH_TABS", "TABS"):
        kbd.send(Keycode.CONTROL, Keycode.TAB)
        last_action = "SWITCH TABS"
    elif action == "ZOOM_IN":
        kbd.send(Keycode.GUI, Keycode.EQUALS)
        last_action = "ZOOM IN"
    elif action == "ZOOM_OUT":
        kbd.send(Keycode.GUI, Keycode.MINUS)
        last_action = "ZOOM OUT"
    elif action == "DESKTOP":
        kbd.send(Keycode.F11)
        last_action = "DESKTOP"
    else:
        return False
    display_dirty = True
    wake_up()
    return True

# ------------- KEYPAD SCANNER -------------
def scan_keypad():
    for r_idx, row in enumerate(rows):
        row.value = False
        for c_idx, col in enumerate(cols):
            if not col.value:
                row.value = True
                return (r_idx + 1, c_idx + 1)
        row.value = True
    return None

# ------------- DISPLAY -------------
def update_display():
    global display_dirty, last_display_time, screen_on
    now = time.monotonic()
    if screen_on and (now - last_input_time > SLEEP_DELAY):
        oled.fill(0)
        oled.show()
        screen_on = False
        return
    if not screen_on:
        return
    if display_dirty and (now - last_display_time > 0.08):
        oled.fill(0)
        oled.text(device_ip, 0, 0, 1, size=1)
        oled.hline(0, 10, 128, 1)
        oled.text(f"VOL: {volume_level}%", 20, 14, 1, size=2)
        oled.rect(5, 33, 118, 8, 1)
        bar_fill = int((volume_level / 100) * 114)
        oled.fill_rect(7, 35, bar_fill, 4, 1)
        oled.text(f"{last_action}", 10, 48, 1, size=2)
        oled.show()
        display_dirty = False
        last_display_time = now

def wake_up():
    global screen_on, last_input_time, display_dirty
    last_input_time = time.monotonic()
    if not screen_on:
        screen_on = True
        display_dirty = True

# ------------- WI-FI COMMAND HANDLING (NON‑BLOCKING) -------------
def handle_http_request(client, request):
    global send_state
    if request.startswith("GET / ") or request.startswith("GET / H"):
        # Prepare the chunk list with IP inserted
        chunks = list(page_chunks)  # copy
        # Insert IP string
        ip_chunk = device_ip.encode()
        chunks[2] = ip_chunk  # index 2 is where we placed the empty bytes for IP
        send_state = {
            "client": client,
            "chunks": chunks,
            "chunk_idx": 0,
            "ip_sent": True
        }
    elif "/status" in request:
        json_resp = (
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n"
            + f'{{"action":"{last_action}","vol":{volume_level}}}'.encode()
        )
        try:
            client.send(json_resp)
        except OSError as e:
            if e.errno != 11:
                raise
            # if would block, we just drop this status request (rare)
        finally:
            client.close()
    elif "/cmd?action=" in request:
        start = request.index("/cmd?action=") + len("/cmd?action=")
        end = request.find(" ", start)
        action = request[start:end] if end != -1 else request[start:]
        if execute_action(action):
            resp = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nOK\n"
        else:
            resp = b"HTTP/1.1 400 Bad Request\r\n\r\n"
        try:
            client.send(resp)
        except OSError as e:
            if e.errno != 11:
                raise
        finally:
            client.close()
    else:
        try:
            client.send(b"HTTP/1.1 404 Not Found\r\n\r\n")
        except OSError:
            pass
        finally:
            client.close()

def process_wifi():
    """Non‑blocking Wi‑Fi handling: accepts new connections and processes chunked sends."""
    global server_sock, client_sock, send_state
    if not wifi.radio.connected:
        init_wifi()
        return

    # Accept new connection if no ongoing send
    if send_state["client"] is None:
        try:
            client_sock, _ = server_sock.accept()
            client_sock.setblocking(False)
        except OSError as e:
            if e.errno == 11:
                client_sock = None
            else:
                client_sock = None
        if client_sock:
            # Read request
            buf = bytearray(512)
            try:
                n = client_sock.recv_into(buf)
            except OSError as e:
                if e.errno == 11:
                    # No data yet, close and retry later
                    client_sock.close()
                    client_sock = None
                    return
                else:
                    client_sock.close()
                    client_sock = None
                    return
            if n == 0:
                client_sock.close()
                client_sock = None
                return
            req = buf[:n].decode("utf-8", "ignore")
            handle_http_request(client_sock, req)
            # For non‑chunked requests, handle_http_request already closed.
            # If it set up a send_state, we let the chunk sender handle closing.

    # Send the next chunk if we have a pending page
    if send_state["client"] is not None:
        client = send_state["client"]
        chunks = send_state["chunks"]
        idx = send_state["chunk_idx"]
        if idx < len(chunks):
            if try_send_all(client, chunks[idx]):
                send_state["chunk_idx"] += 1
            # If try_send_all returned False (would block), we just continue loop
            # and try again next time.
        else:
            # All chunks sent
            client.close()
            send_state["client"] = None
            send_state["chunks"] = []
            send_state["chunk_idx"] = 0

# ------------- MAIN LOOP -------------
print("MacroPad Ready!")
while True:
    # --- Encoder ---
    curr_pos = encoder.position
    delta = curr_pos - last_position
    if delta != 0:
        wake_up()
        delta = max(-5, min(5, delta))
        if current_mode == 0:
            for _ in range(abs(delta)):
                if delta > 0:
                    cc.send(ConsumerControlCode.VOLUME_INCREMENT)
                else:
                    cc.send(ConsumerControlCode.VOLUME_DECREMENT)
            volume_level = max(0, min(100, volume_level + delta * 2))
            last_action = "VOL ADJUST"
        else:
            target_key = Keycode.DOWN_ARROW if delta > 0 else Keycode.UP_ARROW
            if scroll_key_held and scroll_key_held != target_key:
                kbd.release(scroll_key_held)
                scroll_key_held = None
            if not scroll_key_held:
                kbd.press(target_key)
                scroll_key_held = target_key
            scroll_hold_time = time.monotonic()
            last_action = "SCROLL DN" if delta > 0 else "SCROLL UP"
        last_position = curr_pos
        display_dirty = True

    # --- Keypad ---
    key = scan_keypad()
    if key:
        wake_up()
        r, c = key
        mapping = {
            KEY_NEXT_TRACK: "NEXT_TRACK",
            KEY_PREV_TRACK: "PREV_TRACK",
            KEY_PLAY_PAUSE: "PLAY_PAUSE",
            KEY_MUTE: "MUTE",
            KEY_WORKPLACE_RIGHT: "WORKPLACE_RIGHT",
            KEY_QUIT_APP: "QUIT_APP",
            KEY_DICTATION: "DICTATION",
            KEY_MODE_TOGGLE: "MODE_TOGGLE",
            KEY_SCREENSHOT: "SCREENSHOT",
            KEY_COPY: "COPY",
            KEY_PASTE: "PASTE",
            KEY_UNDO: "UNDO",
            KEY_SWITCH_TABS: "SWITCH_TABS",
            KEY_ZOOM_IN: "ZOOM_IN",
            KEY_ZOOM_OUT: "ZOOM_OUT",
            KEY_DESKTOP: "DESKTOP",
        }
        action = mapping.get(key)
        if action:
            execute_action(action)
        time.sleep(0.02)  # simple debounce

    # --- Scroll key release ---
    if scroll_key_held and (time.monotonic() - scroll_hold_time > SCROLL_HOLD_DURATION):
        kbd.release(scroll_key_held)
        scroll_key_held = None

    # --- Wi‑Fi processing (non‑blocking) ---
    process_wifi()

    # --- Display update ---
    update_display()

    # Tiny sleep to keep the loop from burning CPU, but short enough to feel instant
    time.sleep(0.005)
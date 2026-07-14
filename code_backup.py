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

# --- 1. HARDWARE ---
i2c = busio.I2C(board.GP1, board.GP0, frequency=400000)
oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c)

kbd = Keyboard(usb_hid.devices)
cc = ConsumerControl(usb_hid.devices)
encoder = rotaryio.IncrementalEncoder(board.GP14, board.GP15)

# --- 2. PINS ---
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

# --- 3. WIFI SETUP ---
WIFI_SSID = "MANI"
WIFI_PASS = "homies2659"
WIFI_PORT = 80

wifi_socket = None
wifi_client = None
device_ip = "No WiFi"

def wifi_connect():
    global wifi_socket, device_ip
    try:
        print(f"Connecting to {WIFI_SSID}...")
        oled.fill(0)
        oled.text("Connecting...", 5, 28, 1, size=1)
        oled.show()
        wifi.radio.connect(WIFI_SSID, WIFI_PASS)
        device_ip = str(wifi.radio.ipv4_address)
        print(f"Connected. IP: {device_ip}")
        pool = socketpool.SocketPool(wifi.radio)
        wifi_socket = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
        wifi_socket.setsockopt(pool.SOL_SOCKET, pool.SO_REUSEADDR, 1)
        wifi_socket.setblocking(False)
        wifi_socket.bind(("", WIFI_PORT))
        wifi_socket.listen(1)
        print(f"Web UI at http://{device_ip}")
        oled.fill(0)
        oled.text("WiFi OK!", 28, 2, 1, size=1)
        oled.text(device_ip, 4, 18, 1, size=1)
        oled.text("Open browser:", 10, 36, 1, size=1)
        oled.text("http://"+device_ip, 0, 50, 1, size=1)
        oled.show()
        time.sleep(3)
    except Exception as e:
        print(f"WiFi failed: {e}")
        wifi_socket = None
        device_ip = "No WiFi"

wifi_connect()

# --- 4. STATE ---
last_position = encoder.position
volume_level = 50
last_action = "READY"
display_dirty = True
last_display_time = 0
current_mode = 0
screen_on = True
last_input_time = time.monotonic()
SLEEP_DELAY = 30
scroll_key_held = None
scroll_hold_time = 0
SCROLL_HOLD_DURATION = 0.2

# --- 5. KEY MAPPING CONSTANTS ---
# Row 1: Media Controls
KEY_NEXT_TRACK = (1, 1)
KEY_PREV_TRACK = (1, 2)
KEY_PLAY_PAUSE = (1, 3)
KEY_MUTE = (1, 4)

# Row 2: App Controls
KEY_WORKPLACE_RIGHT = (2, 1)  # Ctrl + Right Arrow
KEY_QUIT_APP = (2, 2)         # Cmd + Q
KEY_DICTATION = (2, 3)        # Single tap → double‑Control dictation
KEY_MODE_TOGGLE = (2, 4)      # Toggle Volume/Scroll mode

# Row 3: Edit Controls
KEY_SCREENSHOT = (3, 1)       # Cmd + Shift + 4
KEY_COPY = (3, 2)             # Cmd + C
KEY_PASTE = (3, 3)            # Cmd + V
KEY_UNDO = (3, 4)             # Cmd + Z

# Row 4: System Controls
KEY_SWITCH_TABS = (4, 1)      # Ctrl + Tab
KEY_ZOOM_IN = (4, 2)          # Cmd + Plus (Safari Zoom In)
KEY_ZOOM_OUT = (4, 3)         # Cmd + Minus (Safari Zoom Out)
KEY_DESKTOP = (4, 4)          # F11 Show Desktop

# --- 6. WEB UI HTML ---
HTML_HEAD = b"""HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1"><title>MacroPad</title><style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0a0a0a;color:#fff;font-family:system-ui,sans-serif;padding:12px;max-width:480px;margin:0 auto}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid #222}
.logo{font-size:.75rem;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:#fff}
.ip{font-size:.65rem;color:#444;font-family:monospace}
#status-bar{background:#111;border:1px solid #222;border-radius:10px;padding:10px 14px;margin-bottom:12px;display:flex;align-items:center;gap:10px}
#status{font-size:1rem;font-weight:700;flex:1;color:#fff}
.vol-wrap{display:flex;align-items:center;gap:8px}
.vol-track{width:80px;background:#222;border-radius:4px;height:6px}
.vol-fill{height:6px;background:#4ade80;border-radius:4px;transition:width .2s}
.vol-num{font-size:.7rem;color:#555;min-width:28px;text-align:right;font-family:monospace}
.section{margin-bottom:14px}
.sec-label{font-size:.6rem;color:#444;text-transform:uppercase;letter-spacing:2px;margin-bottom:6px;padding-left:2px}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}
.grid2{display:grid;grid-template-columns:repeat(2,1fr);gap:6px}
btn,button{display:block;width:100%;background:#141414;color:#ccc;border:1px solid #2a2a2a;border-radius:9px;padding:15px 4px;font-size:.72rem;font-weight:700;cursor:pointer;transition:background .1s,transform .08s,border-color .1s;letter-spacing:.3px;text-align:center;-webkit-tap-highlight-color:transparent;user-select:none}
button:active{background:#252525;transform:scale(.95);border-color:#444}
.g{border-color:#4ade8044;color:#4ade80}
.g:active{background:#4ade8015}
.r{border-color:#f8717144;color:#f87171}
.r:active{background:#f8717115}
.b{border-color:#60a5fa44;color:#60a5fa}
.b:active{background:#60a5fa15}
.y{border-color:#fbbf2444;color:#fbbf24}
.y:active{background:#fbbf2415}
.p{border-color:#c084fc44;color:#c084fc}
.p:active{background:#c084fc15}
</style></head><body>"""

HTML_HEADER_PART = b"""<header><div class="logo">&#9632; MacroPad</div><div class="ip">"""
HTML_HEADER_END = b"""</div></header>
<div id="status-bar">
  <div id="status">READY</div>
  <div class="vol-wrap">
    <div class="vol-track"><div class="vol-fill" id="vbar" style="width:50%"></div></div>
    <div class="vol-num" id="vlabel">50%</div>
  </div>
</div>"""

HTML_BODY = b"""
<div class="section">
  <div class="sec-label">Media Controls (Row 1)</div>
  <div class="grid4">
    <button class="b" onclick="cmd('NEXT_TRACK')">&#9654;&#9654;<br>NEXT</button>
    <button class="b" onclick="cmd('PREV_TRACK')">&#9664;&#9664;<br>PREV</button>
    <button class="g" onclick="cmd('PLAY_PAUSE')">&#9654;<br>PLAY</button>
    <button class="r" onclick="cmd('MUTE')">&#128263;<br>MUTE</button>
  </div>
</div>
<div class="section">
  <div class="sec-label">App Controls (Row 2)</div>
  <div class="grid4">
    <button class="b" onclick="cmd('WORKPLACE_RIGHT')">WORKPLACE<br>&#8594;</button>
    <button class="r" onclick="cmd('QUIT_APP')">QUIT<br>APP</button>
    <button class="y" onclick="cmd('DICTATION')">DICTATION<br>(1x Ctrl)</button>
    <button class="p" onclick="cmd('MODE_TOGGLE')">TOGGLE<br>MODE</button>
  </div>
</div>
<div class="section">
  <div class="sec-label">Edit Controls (Row 3)</div>
  <div class="grid4">
    <button class="y" onclick="cmd('SCREENSHOT')">SCREEN<br>SHOT</button>
    <button onclick="cmd('COPY')">COPY</button>
    <button onclick="cmd('PASTE')">PASTE</button>
    <button onclick="cmd('UNDO')">UNDO</button>
  </div>
</div>
<div class="section">
  <div class="sec-label">Browser & System (Row 4)</div>
  <div class="grid4">
    <button class="b" onclick="cmd('SWITCH_TABS')">SWITCH<br>TABS</button>
    <button class="g" onclick="cmd('ZOOM_IN')">ZOOM<br>IN</button>
    <button class="r" onclick="cmd('ZOOM_OUT')">ZOOM<br>OUT</button>
    <button class="y" onclick="cmd('DESKTOP')">DESKTOP</button>
  </div>
</div>
<div class="section">
  <div class="sec-label">Quick Actions</div>
  <div class="grid2">
    <button class="g" onclick="cmd('VOLUP')">&#9650; VOL UP</button>
    <button class="r" onclick="cmd('VOLDN')">&#9660; VOL DN</button>
  </div>
</div>"""

HTML_FOOT = b"""<script>
function cmd(a){
  fetch('/cmd?action='+a).then(()=>poll());
}
function poll(){
  fetch('/status').then(r=>r.json()).then(d=>{
    document.getElementById('status').textContent=d.action;
    document.getElementById('vbar').style.width=d.vol+'%';
    document.getElementById('vlabel').textContent=d.vol+'%';
  });
}
setInterval(poll,1000);
</script></body></html>"""

def status_json():
    return (
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n"
        + f'{{"action":"{last_action}","vol":{volume_level}}}'.encode()
    )

# --- 7. KEYPAD / DISPLAY ---
def scan_keypad():
    for r_idx, row in enumerate(rows):
        row.value = False
        for c_idx, col in enumerate(cols):
            if not col.value:
                row.value = True
                return (r_idx + 1, c_idx + 1)
        row.value = True
    return None

def update_display():
    global display_dirty, last_display_time, screen_on
    now = time.monotonic()
    if screen_on and (now - last_input_time > SLEEP_DELAY):
        oled.fill(0)
        oled.show()
        screen_on = False
        print("Screen Sleeping...")
    if screen_on and display_dirty and (now - last_display_time > 0.08):
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

# --- 8. UNIFIED ACTION HANDLER ---
def execute_action(action):
    """Execute action for both physical buttons and web UI"""
    global volume_level, last_action, current_mode, display_dirty
    
    action = action.strip().upper()
    
    # Media Controls
    if action == "PLAY_PAUSE" or action == "PLAY":
        cc.send(ConsumerControlCode.PLAY_PAUSE)
        last_action = "PLAY/PAUSE"
    
    elif action == "PREV_TRACK" or action == "PREV":
        cc.send(ConsumerControlCode.SCAN_PREVIOUS_TRACK)
        last_action = "PREV TRACK"
    
    elif action == "NEXT_TRACK" or action == "NEXT":
        cc.send(ConsumerControlCode.SCAN_NEXT_TRACK)
        last_action = "NEXT TRACK"
    
    elif action == "MUTE":
        cc.send(ConsumerControlCode.MUTE)
        last_action = "MUTE"
    
    # Volume Controls
    elif action == "VOLUP":
        cc.send(ConsumerControlCode.VOLUME_INCREMENT)
        volume_level = min(100, volume_level + 2)
        last_action = "VOL +2"
    
    elif action == "VOLDN":
        cc.send(ConsumerControlCode.VOLUME_DECREMENT)
        volume_level = max(0, volume_level - 2)
        last_action = "VOL -2"
    
    # App Controls
    elif action == "WORKPLACE_RIGHT" or action == "WORKPLACE":
        kbd.send(Keycode.CONTROL, Keycode.RIGHT_ARROW)
        last_action = "WORKPLACE →"
    
    elif action == "QUIT_APP" or action == "QUIT":
        kbd.press(Keycode.GUI, Keycode.Q)
        time.sleep(0.05)
        kbd.release_all()
        last_action = "QUIT APP"
    
    elif action == "DICTATION" or action == "DICTATE":
        # Double‑press Control key quickly for dictation
        kbd.press(Keycode.CONTROL)
        kbd.release(Keycode.CONTROL)
        time.sleep(0.03)  # Very short delay between presses
        kbd.press(Keycode.CONTROL)
        kbd.release(Keycode.CONTROL)
        last_action = "DICTATION"
    
    elif action == "MODE_TOGGLE" or action == "MODE":
        current_mode = (current_mode + 1) % 2
        last_action = "MODE: VOL" if current_mode == 0 else "MODE: SCRL"
    
    # Edit Controls
    elif action == "SCREENSHOT" or action == "SNIP":
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
    
    # System Controls
    elif action == "SWITCH_TABS" or action == "TABS":
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
    
    # Legacy support
    elif action == "SWITCH":
        kbd.press(Keycode.GUI, Keycode.TAB)
        kbd.release(Keycode.TAB)
        time.sleep(0.1)
        kbd.release_all()
        last_action = "APP SWITCH"
    
    elif action == "DELETE" or action == "FORWARD_DELETE":
        kbd.send(Keycode.DELETE)
        last_action = "FWD DELETE"
    
    else:
        return False
    
    display_dirty = True
    wake_up()
    return True

# --- 9. WIFI COMMAND HANDLER ---
def handle_wifi_command(action):
    return execute_action(action)

def check_wifi():
    global wifi_client
    if wifi_socket is None:
        return
    try:
        wifi_client, _ = wifi_socket.accept()
        wifi_client.setblocking(False)
    except OSError:
        return
    try:
        buf = bytearray(512)
        try:
            n = wifi_client.recv_into(buf)
        except OSError as e:
            if e.errno == 11:
                time.sleep(0.05)
                n = wifi_client.recv_into(buf)
            else:
                raise
        if n == 0:
            return
        req = buf[:n].decode("utf-8", "ignore")

        if req.startswith("GET / ") or req.startswith("GET / H"):
            wifi_client.send(HTML_HEAD)
            wifi_client.send(HTML_HEADER_PART)
            wifi_client.send(device_ip.encode())
            wifi_client.send(HTML_HEADER_END)
            wifi_client.send(HTML_BODY)
            wifi_client.send(HTML_FOOT)

        elif "/status" in req:
            wifi_client.send(status_json())

        elif "/cmd?action=" in req:
            start = req.index("/cmd?action=") + len("/cmd?action=")
            end   = req.find(" ", start)
            action = req[start:end] if end != -1 else req[start:]
            if handle_wifi_command(action):
                wifi_client.send(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nOK\n")
            else:
                wifi_client.send(b"HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nUnknown\n")
        else:
            wifi_client.send(b"HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n")

    except Exception as e:
        print(f"WiFi error: {e}")
    finally:
        wifi_client.close()
        wifi_client = None

# --- 10. MAIN LOOP ---
print("MacroPad Ready!")
print(f"Key Mapping:")
print(f"  Row 1: NEXT | PREV | PLAY | MUTE")
print(f"  Row 2: WORKPLACE → | QUIT APP | DICTATION (1 tap) | MODE TOGGLE")
print(f"  Row 3: SCREENSHOT | COPY | PASTE | UNDO")
print(f"  Row 4: SWITCH TABS | ZOOM IN | ZOOM OUT | DESKTOP")
print(f"  Encoder: Volume (Mode 0) / Scroll (Mode 1)")

while True:
    # --- ENCODER (fixed overflow handling) ---
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

    # --- KEYPAD (Dictation now works on single tap) ---
    key = scan_keypad()
    if key:
        wake_up()
        r, c = key
        
        if (r, c) == KEY_DICTATION:
            execute_action("DICTATION")
        elif (r, c) == KEY_NEXT_TRACK:
            execute_action("NEXT_TRACK")
        elif (r, c) == KEY_PREV_TRACK:
            execute_action("PREV_TRACK")
        elif (r, c) == KEY_PLAY_PAUSE:
            execute_action("PLAY_PAUSE")
        elif (r, c) == KEY_MUTE:
            execute_action("MUTE")
        elif (r, c) == KEY_WORKPLACE_RIGHT:
            execute_action("WORKPLACE_RIGHT")
        elif (r, c) == KEY_QUIT_APP:
            execute_action("QUIT_APP")
        elif (r, c) == KEY_MODE_TOGGLE:
            execute_action("MODE_TOGGLE")
        elif (r, c) == KEY_SCREENSHOT:
            execute_action("SCREENSHOT")
        elif (r, c) == KEY_COPY:
            execute_action("COPY")
        elif (r, c) == KEY_PASTE:
            execute_action("PASTE")
        elif (r, c) == KEY_UNDO:
            execute_action("UNDO")
        elif (r, c) == KEY_SWITCH_TABS:
            execute_action("SWITCH_TABS")
        elif (r, c) == KEY_ZOOM_IN:
            execute_action("ZOOM_IN")
        elif (r, c) == KEY_ZOOM_OUT:
            execute_action("ZOOM_OUT")
        elif (r, c) == KEY_DESKTOP:
            execute_action("DESKTOP")
        
        time.sleep(0.02)  # Debounce

    # --- SCROLL RELEASE ---
    if scroll_key_held and (time.monotonic() - scroll_hold_time > SCROLL_HOLD_DURATION):
        kbd.release(scroll_key_held)
        scroll_key_held = None

    # --- WIFI (with automatic reconnection) ---
    if not wifi.radio.connected:
        print("WiFi lost, reconnecting...")
        wifi_connect()
    check_wifi()

    # --- DISPLAY ---
    update_display()
    time.sleep(0.005)
import time
import board
import busio
import rotaryio
import usb_hid
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

# Key matrix (4×4)
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

# ------------- STATE VARIABLES -------------
last_position = encoder.position
volume_level = 50          # Displayed volume (approximate, steps of 2%)
last_action = "READY"
display_dirty = True
last_display_time = 0
current_mode = 0           # 0 = Volume, 1 = Scroll
screen_on = True
last_input_time = time.monotonic()
SLEEP_DELAY = 30           # OLED sleep after 30 seconds of inactivity

scroll_key_held = None
scroll_hold_time = 0
SCROLL_HOLD_DURATION = 0.2 # Auto-release scroll key after 200ms without movement

# ------------- KEY MAPPING (row, col) -------------
KEY_NEXT_TRACK      = (1, 1)
KEY_PREV_TRACK      = (1, 2)
KEY_PLAY_PAUSE      = (1, 3)
KEY_MUTE            = (1, 4)

KEY_WORKPLACE_RIGHT = (2, 1)   # Ctrl + Right Arrow
KEY_QUIT_APP        = (2, 2)   # Cmd + Q
KEY_DICTATION       = (2, 3)   # Double‑press Control (macOS dictation)
KEY_MODE_TOGGLE     = (2, 4)

KEY_SCREENSHOT      = (3, 1)   # Cmd + Shift + 4
KEY_COPY            = (3, 2)   # Cmd + C
KEY_PASTE           = (3, 3)   # Cmd + V
KEY_UNDO            = (3, 4)   # Cmd + Z

KEY_SWITCH_TABS     = (4, 1)   # Ctrl + Tab
KEY_ZOOM_IN         = (4, 2)   # Cmd + =
KEY_ZOOM_OUT        = (4, 3)   # Cmd + -
KEY_DESKTOP         = (4, 4)   # F11 (show desktop)

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

    # Volume (manual buttons)
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

    # System / Browser
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
    # Sleep after inactivity
    if screen_on and (now - last_input_time > SLEEP_DELAY):
        oled.fill(0)
        oled.show()
        screen_on = False
        return
    if not screen_on:
        return
    # Update only when dirty and at least 80ms since last refresh
    if display_dirty and (now - last_display_time > 0.08):
        oled.fill(0)
        # Top line: mode indicator
        mode_str = "MODE: VOL" if current_mode == 0 else "MODE: SCRL"
        oled.text(mode_str, 0, 0, 1, size=1)
        oled.hline(0, 10, 128, 1)
        # Volume display
        oled.text(f"VOL: {volume_level}%", 20, 14, 1, size=2)
        oled.rect(5, 33, 118, 8, 1)
        bar_fill = int((volume_level / 100) * 114)
        oled.fill_rect(7, 35, bar_fill, 4, 1)
        # Last action
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

# ------------- MAIN LOOP (ZERO‑FREEZE) -------------
print("MacroPad Ready – No Wi‑Fi – macOS optimised")
while True:
    # --- Encoder ---
    curr_pos = encoder.position
    delta = curr_pos - last_position
    if delta != 0:
        wake_up()
        # Cap delta to avoid massive bursts
        delta = max(-5, min(5, delta))
        if current_mode == 0:
            # Volume mode
            for _ in range(abs(delta)):
                if delta > 0:
                    cc.send(ConsumerControlCode.VOLUME_INCREMENT)
                else:
                    cc.send(ConsumerControlCode.VOLUME_DECREMENT)
            volume_level = max(0, min(100, volume_level + delta * 2))
            last_action = "VOL ADJUST"
        else:
            # Scroll mode (arrow keys)
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
        time.sleep(0.02)  # Debounce

    # --- Scroll key auto‑release ---
    if scroll_key_held and (time.monotonic() - scroll_hold_time > SCROLL_HOLD_DURATION):
        kbd.release(scroll_key_held)
        scroll_key_held = None

    # --- Display update ---
    update_display()

    # Tiny sleep to keep CPU cool
    time.sleep(0.001)

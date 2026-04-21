"""
RP2040 OLED Macro Pad

CircuitPython macro pad with:
- 4x4 matrix keypad
- SSD1306 128x64 I2C OLED
- Rotary encoder for volume or scrolling
- USB HID keyboard and consumer control support
"""

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

# --- 3. STATE & SLEEP TIMER ---
last_position = 0
volume_level = 50
last_action = "READY"
display_dirty = True
last_display_time = 0

current_mode = 0  # 0 = Volume, 1 = Scroll

screen_on = True
last_input_time = time.monotonic()
SLEEP_DELAY = 30  # Seconds before OLED turns off

# Non-blocking scroll state
scroll_key_held = None
scroll_hold_time = 0
SCROLL_HOLD_DURATION = 0.2  # Tuned for quick stop with minimal overshoot


# --- 4. FUNCTIONS ---
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
        oled.text(f"VOL: {volume_level}%", 30, 2, 1, size=2)
        oled.rect(5, 25, 118, 10, 1)
        bar_fill = int((volume_level / 100) * 114)
        oled.fill_rect(7, 27, bar_fill, 6, 1)
        oled.text(f"{last_action}", 10, 45, 1, size=2)
        oled.show()

        display_dirty = False
        last_display_time = now


def wake_up():
    global screen_on, last_input_time, display_dirty
    last_input_time = time.monotonic()
    if not screen_on:
        screen_on = True
        display_dirty = True
        print("Screen Waking...")


# --- 5. MAIN LOOP ---
while True:
    # --- ENCODER (VOLUME OR SCROLL) ---
    curr_pos = encoder.position
    if curr_pos != last_position:
        wake_up()
        if current_mode == 0:
            if curr_pos > last_position:
                cc.send(ConsumerControlCode.VOLUME_INCREMENT)
                volume_level = min(100, volume_level + 2)
            else:
                cc.send(ConsumerControlCode.VOLUME_DECREMENT)
                volume_level = max(0, volume_level - 2)
            last_action = "VOLUME"
        else:
            target_key = (
                Keycode.DOWN_ARROW if curr_pos > last_position else Keycode.UP_ARROW
            )

            if scroll_key_held and scroll_key_held != target_key:
                kbd.release(scroll_key_held)
                scroll_key_held = None

            if not scroll_key_held:
                kbd.press(target_key)
                scroll_key_held = target_key

            scroll_hold_time = time.monotonic()
            last_action = "SCROLL DN" if curr_pos > last_position else "SCROLL UP"

        last_position = curr_pos
        display_dirty = True

    # --- KEYPAD ---
    key = scan_keypad()
    if key:
        wake_up()
        r, c = key

        # ==========================================
        # ROW 1 (GP2)
        # ==========================================
        if r == 1 and c == 1:  # App Switcher (Cmd + Tab Hold)
            last_action = "SWITCH"
            update_display()
            kbd.press(Keycode.GUI)
            kbd.press(Keycode.TAB)
            kbd.release(Keycode.TAB)
            while not cols[c - 1].value:
                time.sleep(0.01)
            kbd.release_all()

        elif r == 1 and c == 2:  # Prev Track
            cc.send(ConsumerControlCode.SCAN_PREVIOUS_TRACK)
            last_action = "PREV"

        elif r == 1 and c == 3:  # Play/Pause
            cc.send(ConsumerControlCode.PLAY_PAUSE)
            last_action = "PLAY"

        elif r == 1 and c == 4:  # Next Track
            cc.send(ConsumerControlCode.SCAN_NEXT_TRACK)
            last_action = "NEXT"

        # ==========================================
        # ROW 2 (GP3)
        # ==========================================
        elif r == 2 and c == 1:  # Mission Control (Ctrl + Up)
            kbd.send(Keycode.CONTROL, Keycode.UP_ARROW)
            last_action = "MISSION"

        elif r == 2 and c == 2:  # Quit App (Cmd + Q)
            kbd.send(Keycode.GUI, Keycode.Q)
            last_action = "QUIT APP"

        elif r == 2 and c == 3:  # Mute Audio
            cc.send(ConsumerControlCode.MUTE)
            last_action = "MUTE"

        elif r == 2 and c == 4:  # Toggle encoder mode
            current_mode = (current_mode + 1) % 2
            if current_mode == 0:
                last_action = "MODE: VOL"
            else:
                last_action = "MODE: SCRL"

        # ==========================================
        # ROW 3 (GP4)
        # ==========================================
        elif r == 3 and c == 1:  # Screen Snip (Cmd + Shift + 4)
            kbd.send(Keycode.GUI, Keycode.SHIFT, Keycode.FOUR)
            last_action = "SNIP"

        elif r == 3 and c == 2:  # Copy (Cmd + C)
            kbd.send(Keycode.GUI, Keycode.C)
            last_action = "COPY"

        elif r == 3 and c == 3:  # Paste (Cmd + V)
            kbd.send(Keycode.GUI, Keycode.V)
            last_action = "PASTE"

        elif r == 3 and c == 4:  # Undo (Cmd + Z)
            kbd.send(Keycode.GUI, Keycode.Z)
            last_action = "UNDO"

        # ==========================================
        # ROW 4 (GP5)
        # ==========================================
        elif r == 4 and c == 1:  # Spotlight (Cmd + Space)
            kbd.send(Keycode.GUI, Keycode.SPACE)
            last_action = "SEARCH"

        elif r == 4 and c == 2:  # Lock Screen (Ctrl + Cmd + Q)
            kbd.send(Keycode.CONTROL, Keycode.GUI, Keycode.Q)
            last_action = "LOCK"

        elif r == 4 and c == 3:  # Desktop (F11)
            kbd.send(Keycode.F11)
            last_action = "DESKTOP"

        elif r == 4 and c == 4:  # Enter
            kbd.send(Keycode.ENTER)
            last_action = "ENTER"

        display_dirty = True
        time.sleep(0.15)

    # --- NON-BLOCKING SCROLL RELEASE ---
    if scroll_key_held and (time.monotonic() - scroll_hold_time > SCROLL_HOLD_DURATION):
        kbd.release(scroll_key_held)
        scroll_key_held = None

    # --- UPDATE SCREEN ---
    update_display()
    time.sleep(0.005)

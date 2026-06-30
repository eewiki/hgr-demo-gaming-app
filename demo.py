#!/usr/bin/env python3
"""
Kiosk menu for Raspberry Pi (X11).
Launches games in Firefox kiosk mode, then shows/hides windows on demand.

Dependencies:
    sudo apt install python3-pygame python3-serial python3-pynput xdotool
"""

import glob
import os
import subprocess
import time
import threading
import sys
import serial
import pygame
from pynput import keyboard as pynput_keyboard


BG_COLOR      = (15,  20,  35)
TITLE_COLOR   = (255, 255, 255)
OPTION_COLOR  = (160, 200, 255)
LOADING_COLOR = (120, 120, 140)
FOOTER_COLOR  = (70,  80, 100)
ACCENT_COLOR  = (80, 120, 220)

# ---------------------------------------------------------------------------
# Configuration — edit this section to add/remove games
# ---------------------------------------------------------------------------
GAMES = [
    {
        "name": "Zig Zag",
        "cmd": ["firefox", "--new-instance", "--profile", "zigzag/firefox_profile", "--kiosk", "http://localhost:8080/zigzag/"],
        "image": "zigzag_200+gesture.png",
        "instruction_page": [
            {"type": "text",  "text": "It's easy, simply tap!", "pos": (512, 270), "font": "title_reg", "color": OPTION_COLOR, "align": "center"},
            {"type": "text",  "text": "1. Tap to start the game", "pos": (512, 350), "font": "option", "color": LOADING_COLOR, "align": "center"},
            {"type": "text",  "text": "2. Tap to change direction", "pos": (512, 400), "font": "option", "color": LOADING_COLOR, "align": "center"},
            {"type": "image", "file": "untap_250.png", "pos": (50, 230)},
            {"type": "image", "file": "tap_250.png", "pos": (822, 230)},
        ],
    },
    {
        "name": "Fishy",
        "cmd": ["firefox", "--new-instance", "--profile", "fishy/firefox_profile", "--kiosk", "http://localhost:8080/fishy/"],
        "image": "fishy_200+gesture.png",
        "instruction_page": [
            {"type": "text",  "text": "Move your fish to:", "pos": (128, 270), "font": "title_reg", "color": OPTION_COLOR},
            {"type": "text",  "text": "•  Eat the smaller fish", "pos": (128, 350), "font": "option", "color": LOADING_COLOR},
            {"type": "text",  "text": "•  Avoid the bigger fish!", "pos": (128, 400), "font": "option", "color": LOADING_COLOR},
            {"type": "text",  "text": "← (Re)start the game", "pos": (128, 480), "font": "option", "color": LOADING_COLOR},
            {"type": "text",  "text": "Up", "pos": (880, 190), "font": "option", "color": LOADING_COLOR},
            {"type": "text",  "text": "Down", "pos": (880, 540), "font": "option", "color": LOADING_COLOR},
            {"type": "text",  "text": "Left", "pos": (680, 320), "font": "option", "color": LOADING_COLOR, "align": "center"},
            {"type": "text",  "text": "Right", "pos": (965, 320), "font": "option", "color": LOADING_COLOR, "align": "center"},
            {"type": "image", "file": "fishy_move_380.png", "pos": (655, 190)},
            {"type": "image", "file": "thumbsUp_140.png", "pos": (25, 410)},
        ],
    },
]

# How long (seconds) to wait for each Firefox window to appear after launch
WINDOW_WAIT = 20

# How long (seconds) a nubmer key must be held before switching to that game
GAME_SELECT_HOLD = 1.0

# Per-game Enter key actions
# Each entry is a list of (x, y) coordinates that will be clicked in sequence.
# Set GAME_ENTER_CLICKS[i] to None if Enter should do nothing for that game.
GAME_ENTER_CLICKS = [
    None,                        # Game 1 — no Enter action
    [(533, 367), (533, 246)],    # Game 2 — press OK and PLAY AGAIN
]

# Serial configuration
SERIAL_PORT_GLOB = "/dev/serial/by-id/usb-STMicroelectronics_STM32_HID_CDC_*"
SERIAL_BAUD = 115200

# HTTP server configuration
HTTP_PORT = 8080

# Resolved paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

#-------------------------------------------------------------------------------
# Runtime state
#-------------------------------------------------------------------------------
serial_port = None
game_procs = []
game_wids  = []
menu_wid   = None
screen_size = (0, 0)    # set once pygame initializes

state = {
    "current": "menu",       # "menu" or an integer index into GAMES
    "loading": True,         # True while games are still launching
    "held_key": None,        # (game_idx, press_timestamp) while # key is held
    "instruction_for": None, # game index when current == "instructions"
}


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

def start_http_server():
    """Start Python's built-in HTTP server serving from the script directory."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(HTTP_PORT)],
        cwd=SCRIPT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"HTTP server started on port {HTTP_PORT} (pid {proc.pid})")
    return proc

# ---------------------------------------------------------------------------
# Serial helpers
# ---------------------------------------------------------------------------

def find_serial_port():
    matches = glob.glob(SERIAL_PORT_GLOB)
    if matches:
        return matches[0]
    return None


def init_serial():
    global serial_port
    port = find_serial_port()
    if not port:
        print(f"Warning: no serial device matched '{SERIAL_PORT_GLOB}'")
        return
    try:
        serial_port = serial.Serial(port, SERIAL_BAUD, timeout=1)
        print(f"Serial port {port} opened.")
    except serial.SerialException as e:
        print(f"Warning: could not open serial port {port}: {e}")
        serial_port = None


def send_state(idx):
    """Send 'state:<idx>\n' over serial. idx=0 means menu, idx=N means game N."""
    if serial_port:
        for attempt in range(3):
            if serial_port.is_open:
                try:
                    serial_port.write(f"state:{idx}\n".encode())
                    serial_port.flush()
                    return True
                except serial.SerialException as e:
                    print(f"Serial write error (attempt {attempt + 1}): {e}")
                    try:
                        serial_port.close()
                    except Exception:
                        pass
            print("Attempting to reconnect to serial port...")
            time.sleep(1)
            
            try:
                init_serial()
                print("Reconnected successfully.")
            except serial.SerialException as e:
                print(f"Reconnection failed: {e}")
                
        print("Failed to send state after maximum retries.")
        return False

# ---------------------------------------------------------------------------
# Window management helpers
# ---------------------------------------------------------------------------

def xdo(*args):
    """Run an xdotool command, suppressing output."""
    subprocess.run(["xdotool"] + list(args),
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def get_wid_for_pid(pid, retries=20, delay=1, min_width=400, min_height=300):
    """Poll xdotool until it finds a sufficiently large window for the given PID.
    Filters out early utility windows which are tiny or zero-sized."""
    for _ in range(retries):
        result = subprocess.run(
            ["xdotool", "search", "--pid", str(pid)],
            capture_output=True, text=True
        )
        wids = result.stdout.strip().split()
        for wid in reversed(wids):  # most recently created window first
            geo = subprocess.run(
                ["xdotool", "getwindowgeometry", wid],
                capture_output=True, text=True
            ).stdout
            # geometry output contains "Geometry: WxH"
            for line in geo.splitlines():
                if "Geometry" in line:
                    try:
                        dims = line.split(":")[1].strip()  # e.g. "1920x1080"
                        w, h = map(int, dims.split("x"))
                        if w >= min_width and h >= min_height:
                            return wid
                    except (ValueError, IndexError):
                        pass
        time.sleep(delay)
    return None


def click_at(x, y):
    """Move the mouse to (x, y) and left-click using xdotool."""
    xdo("mousemove", "--sync", str(x), str(y))
    xdo("click", "1")


def raise_wid(wid):
    xdo("windowactivate", str(wid))
    xdo("windowraise", str(wid))


def minimize_wid(wid):
    xdo("windowminimize", str(wid))


def show_menu():
    send_state(0)
    if menu_wid:
        raise_wid(menu_wid)
    state["current"] = "menu"
    state["instructions_for"] = None


def show_instructions(idx):
    """Show the instruction page for game idx — pygame stays on top."""
    send_state(idx + 1)  # game 0 -> state:1, game 1 -> state:2, etc.
    state["current"]          = "instructions"
    state["instructions_for"] = idx


def show_game(idx):
    """Bring the game window to the front and hand off control to Firefox."""
    wid = game_wids[idx] if idx < len(game_wids) else None
    if wid:
        raise_wid(wid)
        xdo("mousemove", str(screen_size[0] - 1), str(screen_size[1] - 1)) # park cursor bottom-right
        state["current"] = idx
        state["instructions_for"] = None


# ---------------------------------------------------------------------------
# Game launcher (runs in a background thread)
# ---------------------------------------------------------------------------

def launch_games():
    """Launch each game in Firefox kiosk mode and record its window ID."""
    for i, game in enumerate(GAMES):
        proc = subprocess.Popen(game["cmd"])
        game_procs.append(proc)

        wid = get_wid_for_pid(proc.pid, retries=WINDOW_WAIT, delay=1, min_width=800, min_height=400)
        game_wids.append(wid)
        
        # Needs a second or minimize_wid() wont be effective
        time.sleep(1)

        if wid:
            minimize_wid(wid)   # hide it until the user asks for it

    state["loading"] = False
    show_menu()


# ---------------------------------------------------------------------------
# Global keyboard listener (active even when Firefox has focus)
# ---------------------------------------------------------------------------

def on_key_press(key):
    """Called by pynput from a background thread for every keypress system-wide."""
    if state["current"] == "menu":
        return  # let pygame handle menu keys

    # Any game is active — watch for ESC to return to menu
    if key == pynput_keyboard.Key.esc:
        show_menu()

    # Space key — trigger configured mouse clicks for the active game
    elif key == pynput_keyboard.Key.space:
        idx = state["current"]
        if isinstance(idx, int):
            clicks = GAME_ENTER_CLICKS[idx] if idx < len(GAME_ENTER_CLICKS) else None
            if clicks:
                for x, y in clicks:
                    click_at(x, y)
                    time.sleep(0.3)  # small delay between clicks
                xdo("mousemove", str(screen_size[0] - 1), str(screen_size[1] - 1)) # park cursor bottom-right


# ---------------------------------------------------------------------------
# Image loading
# ---------------------------------------------------------------------------

def load_thumbnails():
    """Load and scale each game's thumbnail. Returns None for missing images."""
    thumbs = []
    for game in GAMES:
        img_file = game.get("image")
        if img_file:
            path = os.path.join(SCRIPT_DIR, img_file)
            try:
                img = pygame.image.load(path).convert_alpha()
                thumbs.append(img)
            except Exception as e:
                print(f"Warning: could not load image '{path}': {e}")
                thumbs.append(None)
        else:
            thumbs.append(None)
    return thumbs


def load_instruction_pages():
    """Pre-load images in each game's instruction_page. Text elements are left as-is.
    Returns a list (one per game) of resolved element lists ready for rendering."""
    pages = []
    for game in GAMES:
        resolved = []
        for elem in game.get("instruction_page", []):
            if elem["type"] == "image":
                path = os.path.join(SCRIPT_DIR, elem["file"])
                try:
                    surf = pygame.image.load(path).convert_alpha()
                    resolved.append({"type": "image", "surface": surf, "pos": elem["pos"]})
                except Exception as e:
                    print(f"Warning: could not load instruction image '{path}': {e}")
            else:
                resolved.append(elem)  # text elements need no pre-processing
        pages.append(resolved)
    return pages

# ---------------------------------------------------------------------------
# Menu rendering
# ---------------------------------------------------------------------------

def draw_menu(screen, fonts, thumbs):
    W, H = screen.get_size()
    screen.fill(BG_COLOR)

    # Subtle horizontal rule under title
    title_font, title_reg_font, option_font, footer_font = fonts

    title_surf = title_font.render("STM32N6 Edge AI Demo", True, TITLE_COLOR)
    title_rect = title_surf.get_rect(center=(W // 2, H // 5))
    screen.blit(title_surf, title_rect)

    subtitle_surf = footer_font.render("Select and control a game using hand gestures!", True, LOADING_COLOR)
    subtitle_rect = subtitle_surf.get_rect(center=(W // 2, H // 5 + 50))
    screen.blit(subtitle_surf, subtitle_rect)

    pygame.draw.line(screen, ACCENT_COLOR,
                     (W // 8, H // 5 + 85), (7 * W // 8, H // 5 + 85), 2)

    if state["loading"]:
        msg = option_font.render("Loading games, please wait…", True, LOADING_COLOR)
        screen.blit(msg, msg.get_rect(center=(W // 2, H // 2)))
    else:
        n       = len(GAMES)
        # Determine column width from the widest image (or a fallback)
        col_w   = max((t.get_width()  if t else 200 for t in thumbs), default=200)
        col_h   = max((t.get_height() if t else 150 for t in thumbs), default=150)
        padding = (W - n * col_w) // (n + 1)
        top_y   = H // 2 - col_h // 2
        top_y += 60

        for i, game in enumerate(GAMES):
            x     = padding + i * (col_w + padding)
            thumb = thumbs[i] if i < len(thumbs) else None

            if thumb:
                # Centre the image within its column in case sizes differ
                ox = (col_w - thumb.get_width()) // 2
                screen.blit(thumb, (x + ox, top_y))
            else:
                pygame.draw.rect(screen, (40, 50, 70), (x, top_y, col_w, col_h))
                pygame.draw.rect(screen, ACCENT_COLOR, (x, top_y, col_w, col_h), 2)

            name_surf = option_font.render(game["name"], True, OPTION_COLOR)
            screen.blit(name_surf, name_surf.get_rect(
                center=(x + col_w // 3, top_y + col_h + 30)))

    footer = footer_font.render("Remove hand from camera view to return here", True, FOOTER_COLOR)
    screen.blit(footer, footer.get_rect(center=(W // 2, H - 30)))


def draw_instructions(screen, fonts, idx, instruction_pages):
    W, H = screen.get_size()
    screen.fill(BG_COLOR)
 
    title_font, title_reg_font, option_font, footer_font = fonts
    font_map = {"title": title_font, "title_reg": title_reg_font, "option": option_font, "footer": footer_font}
 
    # Title
    title_surf = title_font.render(f"How to Play: {GAMES[idx]['name']}", True, TITLE_COLOR)
    screen.blit(title_surf, title_surf.get_rect(center=(W // 2, H // 5)))
 
    pygame.draw.line(screen, ACCENT_COLOR,
                     (W // 8, H // 5 + 50), (7 * W // 8, H // 5 + 50), 2)
 
    # Render each element at its defined position
    for elem in instruction_pages[idx]:
        if elem["type"] == "image":
            screen.blit(elem["surface"], elem["pos"])
        elif elem["type"] == "text":
            font  = font_map.get(elem.get("font", "option"), option_font)
            color = elem.get("color", OPTION_COLOR)
            surf  = font.render(elem["text"], True, color)
            if ("align" in elem) and (elem["align"] == "center"):
                screen.blit(surf, surf.get_rect(center=elem["pos"]))
            else:
                screen.blit(surf, elem["pos"])
 
    # Footer prompts
    esc_surf = footer_font.render("Remove hand from camera view to return to menu", True, FOOTER_COLOR)
    screen.blit(esc_surf, esc_surf.get_rect(center=(W // 2, H - 30)))

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global menu_wid, screen_size

    pygame.init()
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    pygame.display.set_caption("Demo Menu")
    pygame.mouse.set_visible(False)

    # Grab the X11 window ID of the Pygame window so we can raise it later
    menu_wid = pygame.display.get_wm_info()["window"]

    W, H = screen.get_size()
    screen_size = (W, H)
    fonts = (
        pygame.font.SysFont("DejaVu Sans", max(H // 12, 48), bold=True),
        pygame.font.SysFont("DejaVu Sans", max(H // 12, 48)),
        pygame.font.SysFont("DejaVu Sans", max(H // 18, 36)),
        pygame.font.SysFont("DejaVu Sans", max(H // 28, 24)),
    )

    thumbs = load_thumbnails()
    instruction_pages = load_instruction_pages()

    clock = pygame.time.Clock()

    init_serial()

    http_proc = start_http_server()

    # Launch games in the background so the menu appears immediately
    threading.Thread(target=launch_games, daemon=True).start()

    # Global key listener — catches ESC even when Firefox has focus
    listener = pynput_keyboard.Listener(on_press=on_key_press)
    listener.start()

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:

                if state["current"] == "menu":
                    # Number keys 1–9 (keyboard row and numpad)
                    idx = None
                    if pygame.K_1 <= event.key <= pygame.K_9:
                        idx = event.key - pygame.K_1
                    elif pygame.K_KP1 <= event.key <= pygame.K_KP9:
                        idx = event.key - pygame.K_KP1

                    if idx is not None and idx < len(GAMES):
                        if not state["loading"] and idx < len(game_wids) and game_wids[idx]:
                            state["held_key"] = (idx, time.monotonic())
                        # If still loading, just do nothing (or add a "not ready" flash)

                    # Quit shortcut for the operator (Ctrl+Q)
                    elif event.key == pygame.K_q and (pygame.key.get_mods() & (pygame.KMOD_LCTRL | pygame.KMOD_RCTRL)):
                        running = False

                elif state["current"] == "instructions":
                    idx = state["instructions_for"]
                    if event.key == pygame.K_SPACE:
                        # User is ready — bring the game window forward
                        show_game(idx)
                    elif event.key == pygame.K_ESCAPE:
                        show_menu()

            elif event.type == pygame.KEYUP and state["current"] == "menu":
                # Cancel if the key is released before the hold threshold
                if state["held_key"] is not None:
                    state["held_key"] = None

        # Check if a number key has been held long enough to switch games
        if state["held_key"] is not None:
            idx, press_time = state["held_key"]
            if time.monotonic() - press_time >= GAME_SELECT_HOLD:
                state["held_key"] = None
                show_instructions(idx)

        # Only draw when the menu is on top (saves CPU while a game is playing)
        if state["current"] == "menu":
            draw_menu(screen, fonts, thumbs)
            pygame.display.flip()
        elif state["current"] == "instructions":
            draw_instructions(screen, fonts, state["instructions_for"], instruction_pages)
            pygame.display.flip()

        clock.tick(30)

    # Cleanup
    listener.stop()
    for proc in game_procs:
        proc.terminate()
    http_proc.terminate()
    pygame.quit()
    sys.exit(0)


if __name__ == "__main__":
    main()

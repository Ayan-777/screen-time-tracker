import os
import time
import sqlite3
import datetime
import win32gui
import win32process
import win32api
import psutil

# Save screentime.db in the project root directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "screentime.db")

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS app_usage (
        date TEXT,
        app_name TEXT,
        seconds INTEGER DEFAULT 0,
        PRIMARY KEY (date, app_name)
    )
''')
conn.commit()

# Friendly display names for common Windows executables
FRIENDLY_NAMES = {
    "code.exe": "VS Code",
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "explorer.exe": "File Explorer",
    "windowsterminal.exe": "Windows Terminal",
    "powershell.exe": "PowerShell",
    "spotify.exe": "Spotify",
    "discord.exe": "Discord",
    "valorant-win64-shipping.exe": "Valorant",
}

def get_idle_duration():
    """Returns idle time in seconds using Windows LastInputInfo."""
    last_input = win32api.GetLastInputInfo()
    current_tick = win32api.GetTickCount()
    elapsed = (current_tick - last_input) & 0xFFFFFFFF
    return elapsed / 1000.0

def get_active_app():
    """Gets a clean name for the active foreground window's process."""
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    if pid <= 0:
        return None
    try:
        process = psutil.Process(pid)
        exe_name = process.name()
        lower_name = exe_name.lower()
        if lower_name in ("lockapp.exe", "idle", "applicationframehost.exe"):
            return None
        return FRIENDLY_NAMES.get(lower_name, exe_name.replace(".exe", "").replace(".EXE", "").capitalize())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None

CHECK_INTERVAL = 2   # Poll every 2 seconds
IDLE_THRESHOLD = 60  # Stop counting after 60s of inactivity

if __name__ == "__main__":
    print(f"Tracking started! Database: {DB_PATH}")
    print("Press Ctrl+C to stop.\n")
    try:
        while True:
            if get_idle_duration() < IDLE_THRESHOLD:
                app_name = get_active_app()
                if app_name:
                    # Midnight rollover happens automatically via today's date string
                    today_str = datetime.date.today().strftime("%Y-%m-%d")
                    cursor.execute('''
                        INSERT INTO app_usage (date, app_name, seconds)
                        VALUES (?, ?, ?)
                        ON CONFLICT(date, app_name) DO UPDATE SET
                        seconds = seconds + ?
                    ''', (today_str, app_name, CHECK_INTERVAL, CHECK_INTERVAL))
                    conn.commit()
                    print(f"[{today_str}] {app_name}: +{CHECK_INTERVAL}s")
            
            time.sleep(CHECK_INTERVAL)
    except KeyboardInterrupt:
        print("\nTracker stopped safely.")
    finally:
        conn.close()
import os
import sys
import json
import time
import ctypes
import sqlite3
import datetime
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import win32gui
import win32process
import win32api
import psutil
import webview

# Set Windows AppUserModelID so the .exe icon can be pinned to the Taskbar properly
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ayan.screentime.tracker.1.0")

# Store database safely in AppData when compiled as .exe, or project root in dev
if getattr(sys, 'frozen', False):
    DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ScreenTimeTracker")
    os.makedirs(DATA_DIR, exist_ok=True)
    DB_PATH = os.path.join(DATA_DIR, "screentime.db")
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DB_PATH = os.path.join(BASE_DIR, "screentime.db")

PORT = 8765

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
    "screentime.exe": "Screen Time",
}

def get_idle_duration():
    last_input = win32api.GetLastInputInfo()
    current_tick = win32api.GetTickCount()
    return ((current_tick - last_input) & 0xFFFFFFFF) / 1000.0

def get_active_app():
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    if pid <= 0:
        return None
    try:
        exe_name = psutil.Process(pid).name()
        lower_name = exe_name.lower()
        if lower_name in ("lockapp.exe", "idle", "applicationframehost.exe"):
            return None
        return FRIENDLY_NAMES.get(lower_name, exe_name.replace(".exe", "").replace(".EXE", "").capitalize())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None

def background_tracker():
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
    while True:
        try:
            if get_idle_duration() < 60:
                app_name = get_active_app()
                if app_name:
                    today_str = datetime.date.today().strftime("%Y-%m-%d")
                    cursor.execute('''
                        INSERT INTO app_usage (date, app_name, seconds)
                        VALUES (?, ?, 2)
                        ON CONFLICT(date, app_name) DO UPDATE SET
                        seconds = seconds + 2
                    ''', (today_str, app_name))
                    conn.commit()
            time.sleep(2)
        except Exception:
            time.sleep(2)

def get_dashboard_data():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS app_usage (
            date TEXT,
            app_name TEXT,
            seconds INTEGER DEFAULT 0,
            PRIMARY KEY (date, app_name)
        )
    ''')
    today = datetime.date.today()
    today_str = today.strftime("%Y-%m-%d")
    
    days_since_sunday = (today.weekday() + 1) % 7
    sunday = today - datetime.timedelta(days=days_since_sunday)
    
    week_days = []
    for i in range(7):
        day = sunday + datetime.timedelta(days=i)
        day_str = day.strftime("%Y-%m-%d")
        cursor.execute("SELECT COALESCE(SUM(seconds), 0) FROM app_usage WHERE date = ?", (day_str,))
        total_sec = cursor.fetchone()[0]
        week_days.append({
            "label": day.strftime("%a"),
            "date": day_str,
            "seconds": total_sec,
            "is_today": day_str == today_str
        })
        
    cursor.execute('''
        SELECT app_name, seconds 
        FROM app_usage 
        WHERE date = ? 
        ORDER BY seconds DESC
    ''', (today_str,))
    apps = [{"name": row[0], "seconds": row[1]} for row in cursor.fetchall()]
    conn.close()
    
    total_today = sum(a["seconds"] for a in apps)
    return {
        "today_formatted": today.strftime("%a, %b %d"),
        "total_today": total_today,
        "week": week_days,
        "apps": apps
    }

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Screen Time</title>
<style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', Roboto, sans-serif; user-select: none; }
    body { background-color: #1a1110; color: #f5ebe6; display: flex; justify-content: center; padding: 24px 18px; }
    .container { width: 100%; max-width: 400px; }
    h1 { font-size: 26px; font-weight: 400; margin-bottom: 20px; color: #ede0d4; }
    .pill { display: inline-block; background: #5c2c26; color: #ffdad4; padding: 7px 18px; border-radius: 20px; font-size: 13px; margin-bottom: 16px; }
    .center-header { text-align: center; }
    .total-time { font-size: 34px; font-weight: 400; margin-bottom: 4px; }
    .sub-label { color: #b8a6a2; font-size: 13px; margin-bottom: 24px; }
    .chart-box { position: relative; height: 170px; display: flex; align-items: flex-end; justify-content: space-between; padding: 10px 35px 25px 10px; border-bottom: 1px solid #3d2f2d; margin-bottom: 20px; }
    .grid-lines { position: absolute; top: 0; left: 0; right: 35px; bottom: 25px; display: flex; flex-direction: column; justify-content: space-between; pointer-events: none; }
    .grid-line { border-top: 1px solid #362826; width: 100%; position: relative; }
    .grid-line span { position: absolute; right: -28px; top: -9px; font-size: 11px; color: #9c8984; }
    .bar-col { display: flex; flex-direction: column; align-items: center; width: 12%; z-index: 2; height: 100%; justify-content: flex-end; }
    .bar { width: 20px; background: #fff8f6; border-radius: 4px 4px 0 0; transition: height 0.3s ease; min-height: 2px; }
    .bar.today { background: #ffb4a8; }
    .day-lbl { margin-top: 8px; font-size: 11px; color: #b8a6a2; position: absolute; bottom: 2px; }
    .date-title { text-align: center; color: #d8c2bc; font-size: 14px; margin: 16px 0; }
    .app-list { display: flex; flex-direction: column; gap: 14px; }
    .app-item { display: flex; align-items: center; justify-content: space-between; padding: 4px 0; }
    .app-left { display: flex; align-items: center; gap: 14px; }
    .app-icon { width: 40px; height: 40px; border-radius: 12px; background: #3b2825; display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 17px; color: #ffb4a8; }
    .app-name { font-size: 16px; color: #f5ebe6; }
    .app-time { font-size: 12px; color: #b8a6a2; margin-top: 2px; }
</style>
</head>
<body>
<div class="container">
    <h1>App activity details</h1>
    <div class="center-header">
        <div class="pill">Screen time ▾</div>
        <div class="total-time" id="totalTime">0 min</div>
        <div class="sub-label">Today</div>
    </div>
    <div class="chart-box">
        <div class="grid-lines">
            <div class="grid-line"><span>8h</span></div>
            <div class="grid-line"><span>6h</span></div>
            <div class="grid-line"><span>4h</span></div>
            <div class="grid-line"><span>2h</span></div>
            <div class="grid-line"><span>0h</span></div>
        </div>
        <div id="barsContainer" style="display:flex; width:100%; height:100%; align-items:flex-end; justify-content:space-between;"></div>
    </div>
    <div class="date-title" id="dateTitle">Today</div>
    <div class="app-list" id="appList"></div>
</div>
<script>
function formatDuration(sec) {
    if (sec < 60) return sec + " sec";
    const hrs = Math.floor(sec / 3600);
    const mins = Math.floor((sec % 3600) / 60);
    if (hrs > 0) return `${hrs} hr, ${mins} min`;
    return `${mins} minutes`;
}
async function loadData() {
    const res = await fetch('/api/data');
    const data = await res.json();
    document.getElementById('totalTime').innerText = formatDuration(data.total_today);
    document.getElementById('dateTitle').innerText = data.today_formatted;
    const maxSeconds = 8 * 3600;
    document.getElementById('barsContainer').innerHTML = data.week.map(d => {
        const heightPct = Math.min(100, (d.seconds / maxSeconds) * 100);
        return `<div class="bar-col">
            <div class="bar ${d.is_today ? 'today' : ''}" style="height: ${heightPct}%" title="${formatDuration(d.seconds)}"></div>
            <span class="day-lbl">${d.label}</span>
        </div>`;
    }).join('');
    document.getElementById('appList').innerHTML = data.apps.map(a => `
        <div class="app-item">
            <div class="app-left">
                <div class="app-icon">${a.name.charAt(0).toUpperCase()}</div>
                <div>
                    <div class="app-name">${a.name}</div>
                    <div class="app-time">${formatDuration(a.seconds)}</div>
                </div>
            </div>
        </div>
    `).join('') || '<div style="text-align:center;color:#9c8984;">No activity recorded yet today</div>';
}
loadData();
setInterval(loadData, 2000);
</script>
</body>
</html>
"""

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/data':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(get_dashboard_data()).encode('utf-8'))
        else:
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode('utf-8'))
    def log_message(self, format, *args):
        return

def start_server():
    server = HTTPServer(("127.0.0.1", PORT), DashboardHandler)
    server.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=background_tracker, daemon=True).start()
    threading.Thread(target=start_server, daemon=True).start()
    
    # Open native desktop window instead of external browser
    webview.create_window(
        "Screen Time",
        f"http://127.0.0.1:{PORT}",
        width=440,
        height=720,
        background_color="#1a1110",
        resizable=True
    )
    webview.start()
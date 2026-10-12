"""
Room security dashboard - one file, standard library only.

Shows live motion status for each corner. The buzzer/alarm is entirely
manual: it only turns on when you press "Sound alarm" on the dashboard,
and off when you press "Silence alarm". Nothing triggers it automatically.

Setup:
    1. Edit BOARDS below with each ESP32's IP address (give them DHCP
       reservations on your router so the IPs don't change).
    2. python3 server.py
    3. Open http://<this-laptop-ip>:8080

For remote access, install Tailscale on this laptop and on your phone, then
open http://<laptop-tailscale-ip>:8080 from anywhere.
"""

import json
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------- CONFIGURE
BOARDS = {
    "Corner NW": "192.168.1.101",
    "Corner NE": "192.168.1.102",
    "Corner SW": "192.168.1.103",
    "Corner SE": "192.168.1.104",
}
WEB_PORT = 8080

POLL_EVERY = 1.0        # seconds between checks of each board
OCCUPIED_HOLD = 20      # "someone is in the room" stays lit this long after motion
OFFLINE_AFTER = 5       # seconds without a good reply before a board shows OFFLINE
# ----------------------------------------------------------------------------

state = {
    name: {"motion": False, "last_motion": 0.0, "ok": False, "last_ok": 0.0}
    for name in BOARDS
}
alarm_active = False
lock = threading.Lock()
events = []


def log(message):
    line = "{}  {}".format(time.strftime("%H:%M:%S"), message)
    events.append(line)
    del events[:-100]
    print(line)


def poll_board(name, ip):
    try:
        with urllib.request.urlopen("http://{}/".format(ip), timeout=1.5) as resp:
            data = json.loads(resp.read())
        with lock:
            s = state[name]
            was_moving = s["motion"]
            s["motion"] = bool(data.get("motion"))
            s["ok"] = True
            s["last_ok"] = time.time()
            if s["motion"]:
                s["last_motion"] = time.time()
            if s["motion"] and not was_moving:
                log("Motion: " + name)
    except Exception:
        with lock:
            state[name]["ok"] = False


def set_buzzers(on):
    for ip in BOARDS.values():
        try:
            urllib.request.urlopen("http://{}/buzz?on={}".format(ip, 1 if on else 0), timeout=1)
        except Exception:
            pass  # that board is unreachable; others still get the command


def evaluate():
    # Only marks boards offline if they've stopped replying. The buzzer is
    # never triggered from here - only the dashboard buttons control it
    # (see do_POST: /api/test and /api/silence).
    now = time.time()
    with lock:
        for s in state.values():
            if now - s["last_ok"] > OFFLINE_AFTER:
                s["ok"] = False


def poll_loop():
    while True:
        threads = [threading.Thread(target=poll_board, args=(n, ip)) for n, ip in BOARDS.items()]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        evaluate()
        time.sleep(POLL_EVERY)


def snapshot():
    now = time.time()
    with lock:
        boards = [{"name": n, "motion": s["motion"], "ok": s["ok"]} for n, s in state.items()]
        occupied = any(now - s["last_motion"] < OCCUPIED_HOLD for s in state.values())
    return {
        "boards": boards,
        "alarm": alarm_active,
        "occupied": occupied,
        "events": events[-20:],
    }


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Room security</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font-family:sans-serif;max-width:640px;margin:2em auto;padding:0 1em;background:#111;color:#eee}
#banner{padding:1em;border-radius:8px;font-weight:bold;text-align:center;font-size:1.3em;color:#fff}
#presence{padding:0.6em;border-radius:8px;text-align:center;margin:0.5em 0}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:0.5em;margin:1em 0}
.card{padding:1em;border-radius:8px;text-align:center;font-weight:bold;color:#fff}
button{padding:0.6em 1.2em;margin:0.3em 0.3em 0.3em 0;border:none;border-radius:6px;cursor:pointer;font-size:1em;color:#fff}
#log{background:#000;padding:0.5em;height:150px;overflow-y:auto;font-family:monospace;font-size:0.85em;border-radius:6px}
</style></head>
<body>
<h1>Room security</h1>
<div id="banner">loading...</div>
<div id="presence"></div>
<div class="grid" id="grid"></div>
<div>
<button style="background:#c62828" onclick="cmd('sound')">Sound alarm</button>
<button style="background:#546e7a" onclick="cmd('silence')">Silence alarm</button>
</div>
<h3>Event log</h3>
<div id="log"></div>
<script>
function cmd(c) { fetch('/api/' + c, {method: 'POST'}); }
async function refresh() {
  const d = await (await fetch('/api/status')).json();
  const b = document.getElementById('banner');
  if (d.alarm) { b.textContent = 'ALARM SOUNDING'; b.style.background = '#c62828'; }
  else { b.textContent = 'Alarm off'; b.style.background = '#546e7a'; }
  const p = document.getElementById('presence');
  p.textContent = d.occupied ? 'Someone is in the room' : 'Room quiet';
  p.style.background = d.occupied ? '#ffcdd2' : '#e8f5e9';
  p.style.color = d.occupied ? '#b71c1c' : '#1b5e20';
  const g = document.getElementById('grid'); g.innerHTML = '';
  d.boards.forEach(x => {
    const c = document.createElement('div'); c.className = 'card';
    if (!x.ok) { c.style.background = '#757575'; c.textContent = x.name + ': OFFLINE'; }
    else if (x.motion) { c.style.background = '#c62828'; c.textContent = x.name + ': MOTION'; }
    else { c.style.background = '#2e7d32'; c.textContent = x.name + ': clear'; }
    g.appendChild(c);
  });
  document.getElementById('log').innerHTML = d.events.slice().reverse().join('<br>');
}
setInterval(refresh, 1000);
refresh();
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # keep the console quiet

    def _send(self, code, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self._send(200, PAGE, "text/html")
        elif self.path == "/api/status":
            self._send(200, json.dumps(snapshot()))
        else:
            self._send(404, "{}")

    def do_POST(self):
        global alarm_active
        if self.path == "/api/sound":
            alarm_active = True
            set_buzzers(True)
            log("Alarm sounded (manual)")
        elif self.path == "/api/silence":
            alarm_active = False
            set_buzzers(False)
            log("Alarm silenced")
        self._send(200, "{}")


if __name__ == "__main__":
    threading.Thread(target=poll_loop, daemon=True).start()
    print("Dashboard running: http://<this-laptop-ip>:{}".format(WEB_PORT))
    ThreadingHTTPServer(("0.0.0.0", WEB_PORT), Handler).serve_forever()

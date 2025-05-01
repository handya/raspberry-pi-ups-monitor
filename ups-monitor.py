from flask import Flask, jsonify, render_template_string, send_file, send_from_directory, request as flask_request
from gpiozero import DigitalInputDevice
from collections import deque
import threading
import requests
import time
import os
from gpiozero import LED
import json

TEST_MODE = False
LOW_BATTERY_SHUTDOWN_DELAY = 30  # seconds
shutdown_timer = None

app = Flask(__name__)

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'log.jsonl')
log_buffer = deque(maxlen=100)
event_start_times = {}

# Load previous logs into memory
if os.path.exists(LOG_FILE):
    with open(LOG_FILE, "r") as f:
        for line in f.readlines()[-100:]:
            try:
                log_buffer.append(json.loads(line))
            except json.JSONDecodeError:
                continue

ups_fault_led = LED(25)
network_led = LED(4)

# GPIO signal mapping
UPS_SIGNALS = {
    "on_ups": DigitalInputDevice(18),
    "on_battery": DigitalInputDevice(17),
    "ups_fault": DigitalInputDevice(27),
    "low_battery": DigitalInputDevice(22),
    "on_bypass": DigitalInputDevice(23),
    "alarm": DigitalInputDevice(24),
    "ups_connected": DigitalInputDevice(15),
}

# Initial state
current_state = {name: False for name in UPS_SIGNALS}
previous_state = current_state.copy()

state_lock = threading.Lock()

WEBHOOKS = {
    "on_battery": "http://10.1.1.60:8123/api/webhook/ups_on_battery",
    "low_battery": "http://10.1.1.60:8123/api/webhook/ups_low_battery",
    "ups_fault": "http://10.1.1.60:8123/api/webhook/ups_fault",
}

timer_start = {
    "on_battery": None,
    "low_battery": None,
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>UPS Monitor</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="/static/shared.js"></script>
    <style>
        body { font-family: sans-serif; background: #111; color: white; text-align: center; }
        .status { 
            margin-top: 20px; 
            font-size: 18px; 
            display: flex;
            flex-direction: column;
            align-items:center; 
        }
        .error { color: red; font-weight: bold; margin-top: 10px; }
        .on { fill: lime; stroke: lime; }
        .off { fill: #444; stroke: #444; }
        .flow-line { stroke-width: 3; stroke-dasharray: 6,4; fill: none; }
        svg {
            width: 100%;  /* scale SVG to container */
            max-width: 500px; /* cap max size on desktop */
            height: auto;
        }
        .bell {
            position: absolute;
            width: 30px;
            height: 30px;
            background-image: url('/static/bell-sprite.png');
            background-repeat: no-repeat;
            background-size: 240px 30px; /* 8 frames × 30px */
            display: none;
        }
        .status-line {
            display: flex;
            width: 120px;
            align-items: center;
            justify-content: left;
            margin: 5px 0;
        }
        .time-line {
            display: flex;
            width: 300px;
            align-items: center;
            justify-content: center;
            margin: 5px 0;
        }
        .indicator {
            width: 15px;
            height: 15px;
            border-radius: 50%;
            margin-right: 8px;
            flex-shrink: 0;
            display: inline-block;
        }
        .indicator-on {
            background-color: lime;
        }
        .indicator-off {
            background-color: #444;
        }
        .indicator-fault {
            background-color: red;
        }
        table { 
            margin: auto; 
            width: 100%;  /* changed from 500px to 100% */
            max-width: 600px; /* keep it nice on desktop */
            background: #222; 
            border-collapse: collapse; 
            box-sizing: border-box; 
        }
        th, td { border: 1px solid #333; padding: 5px; }
        .container {
            padding: 10px;
            box-sizing: border-box;
        }
        .see-all-btn {
            background: none;
            border: none;
            color: #0a84ff;  /* iOS blue */
            font-size: 16px;
            cursor: pointer;
            padding: 0;
            display: flex;
            align-items: center;
        }

        .see-all-btn:focus {
            outline: none;
        }

        .chevron {
            font-size: 18px;
            margin-left: 4px;
        }
    </style>
</head>
<body>
<div class="container">
    <div id="disconnect-overlay" style="
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, 0.7);
        color: red;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 32px;
        font-weight: bold;
        z-index: 9999;
        display: none;
    ">
        UPS Disconnected
    </div>

    <h1>UPS Status</h1>

    <div id="svg-container" style="position: relative; display: inline-block;">

        <svg id="ups-diagram" width="500" height="300" viewBox="0 0 500 300">
            <!-- UPS Box (around inverter and battery) -->
            <rect x="150" y="60" width="200" height="220" stroke="gray" stroke-width="2" fill="none" />

            <line id="mains-inverter" x1="80" y1="150" x2="220" y2="150" class="flow-line" />
            <line id="inverter-load" x1="280" y1="150" x2="420" y2="150" class="flow-line" />
            <line id="battery-inverter" x1="250" y1="210" x2="250" y2="175" class="flow-line" />

            <path id="on-line-bypass" d="
                M 80 150 H 180
                V 80
                H 320
                V 150
                H 430
            " class="flow-line" />

            <path id="bypass-line" d="
                M 80 150 H 120
                V 20
                H 380
                V 150
                H 430
            " class="flow-line" />

            <rect id="mains" x="20" y="125" width="60" height="50" />
            <text x="50" y="115" fill="white" text-anchor="middle">Mains</text>

            <rect id="inverter" x="220" y="125" width="60" height="50" />
            <text x="250" y="115" fill="white" text-anchor="middle">Inverter</text>

            <rect id="load" x="420" y="125" width="60" height="50" />
            <text x="450" y="115" fill="white" text-anchor="middle">Load</text>

            <rect id="battery" x="220" y="210" width="60" height="50" />
            <text x="250" y="205" fill="white" text-anchor="middle">Battery</text>

            <text x="250" y="45" fill="white" text-anchor="middle">UPS</text>
        </svg>

        <div id="bell-mains" class="bell"></div>
        <div id="bell-inverter" class="bell"></div>
        <div id="bell-battery" class="bell"></div>
    </div>

    <div class="status" id="status-text">
        Loading...
    </div>
    <div class="status" id="time-text">
        Loading...
    </div>

    <h3 style="display: flex; justify-content: space-between; align-items: center; margin: auto; width: 100%; max-width: 600px; padding-bottom: 16px; padding-top: 32px;">
        Recent Logs
        <button class="see-all-btn" onclick="window.location='/logs'">
            See All Logs <span class="chevron">›</span>
        </button>
    </h3>
    <table>
        <thead><tr><th>Time</th><th>Ago</th><th>Event</th><th>State</th><th>Duration</th></tr></thead>
        <tbody>
        </tbody>
    </table>

    <div id="error-text" class="error" style="display:none;">
        Error: Unable to contact UPS monitor
    </div>

    <script>
        const bellMains = document.getElementById('bell-mains');
        const bellInverter = document.getElementById('bell-inverter');
        const bellBattery = document.getElementById('bell-battery');
        const errorText = document.getElementById('error-text');
        let frame = 0;

        setInterval(() => {
            const offset = `-${frame * 30}px 0px`;
            bellMains.style.backgroundPosition = offset;
            bellInverter.style.backgroundPosition = offset;
            bellBattery.style.backgroundPosition = offset;
            frame = (frame + 1) % 8;
        }, 500);

        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                if (!res.ok) throw new Error('HTTP error');
                const data = await res.json();
                updateDisplay(data);
                errorText.style.display = 'none';
            } catch (err) {
                console.error('Failed to fetch status', err);
                errorText.style.display = 'block';
            }
        }

        function updateDisplay(states) {
            document.getElementById('mains').setAttribute('class', states.on_battery ? 'off' : 'on');
            document.getElementById('inverter').setAttribute('class', states.ups_fault ? 'off' : 'on');
            document.getElementById('load').setAttribute('class', states.on_ups ? 'on' : 'off');
            document.getElementById('battery').setAttribute('class', states.on_battery ? 'on' : 'off');

            // Handle UPS disconnect
            if (states.ups_connected) {
                document.getElementById('disconnect-overlay').style.display = 'none';
            } else {
                document.getElementById('disconnect-overlay').style.display = 'flex';
            }

            if (states.on_bypass) {
                document.getElementById('bypass-line').setAttribute('stroke', 'lime');
                document.getElementById('battery-inverter').setAttribute('stroke', '#444');
                document.getElementById('inverter-load').setAttribute('stroke', '#444');
                document.getElementById('on-line-bypass').setAttribute('stroke', 'none');
                document.getElementById('mains-inverter').setAttribute('stroke', '#444');

            } else if (states.on_battery) {
                document.getElementById('battery-inverter').setAttribute('stroke', 'lime');
                document.getElementById('inverter-load').setAttribute('stroke', 'lime');
                document.getElementById('bypass-line').setAttribute('stroke', 'none');
                document.getElementById('on-line-bypass').setAttribute('stroke', 'none');
                document.getElementById('mains-inverter').setAttribute('stroke', '#444');
                document.getElementById('battery-inverter').setAttribute('stroke', 'lime');
            } else {
                document.getElementById('battery-inverter').setAttribute('stroke', 'lime');
                document.getElementById('inverter-load').setAttribute('stroke', '#444');
                document.getElementById('bypass-line').setAttribute('stroke', states.on_bypass ? 'lime' : 'none');
                document.getElementById('on-line-bypass').setAttribute('stroke', states.on_ups ? 'lime' : 'none');
                document.getElementById('mains-inverter').setAttribute('stroke', '#444');
                document.getElementById('battery-inverter').setAttribute('stroke', '#444');
                document.getElementById('battery').setAttribute('class', states.ups_fault ? 'off' : 'on');
            }

            if (states.on_battery) {
                bellMains.style.display = 'block';
                bellMains.style.top = '165px';
                bellMains.style.left = '20px';
                bellMains.style.transform = 'translate(15px, 10px)';
            } else {
                bellMains.style.display = 'none';
            }

            if (states.ups_fault) {
                bellInverter.style.display = 'block';
                bellInverter.style.top = '165px';
                bellInverter.style.left = '220px';
                bellInverter.style.transform = 'translate(15px, 10px)';
            } else {
                bellInverter.style.display = 'none';
            }

            if (states.low_battery) {
                bellBattery.style.display = 'block';
                bellBattery.style.top = '250px';
                bellBattery.style.left = '220px';
                bellBattery.style.transform = 'translate(15px, 10px)';
            } else {
                bellBattery.style.display = 'none';
            }

            const statusText = `
                <div class="status-line"><span class="indicator ${states.on_ups ? 'indicator-on' : 'indicator-off'}"></span>On UPS</div>
                <div class="status-line"><span class="indicator ${states.on_battery ? 'indicator-fault' : 'indicator-off'}"></span>On Battery</div>
                <div class="status-line"><span class="indicator ${states.ups_fault ? 'indicator-fault' : 'indicator-off'}"></span>UPS Fault</div>
                <div class="status-line"><span class="indicator ${states.low_battery ? 'indicator-fault' : 'indicator-off'}"></span>Low Battery</div>
                <div class="status-line"><span class="indicator ${states.on_bypass ? 'indicator-fault' : 'indicator-off'}"></span>On Bypass</div>
                <div class="status-line"><span class="indicator ${states.alarm ? 'indicator-fault' : 'indicator-off'}"></span>Alarm</div>
            `;
            document.getElementById('status-text').innerHTML = statusText;

            const timeText = `
                <div class="time-line">Battery Runtime:&nbsp;${states.battery_runtime}</div>
                <div class="time-line">Low Battery Duration:&nbsp;${states.low_battery_duration}</div>
                <div class="time-line">System Uptime:&nbsp;${states.system_uptime}</div>
            `;
            document.getElementById('time-text').innerHTML = timeText;

            if (states.recent_logs && Array.isArray(states.recent_logs)) {
                const tableBody = document.querySelector('table tbody');
                // Sort from newest to oldest (assuming latest at end of array)
                const sortedLogs = states.recent_logs.slice().reverse();
                tableBody.innerHTML = '';
                sortedLogs.forEach(log => {
                    const row = `<tr>
                        <td>${log.timestamp}</td>
                        <td>${timeAgo(log.timestamp)}</td>
                        <td>${formatEventName(log.event)}</td>
                       <td><span class="indicator ${getIndicatorClass(log.event, log.state)}"></span></td>
                        <td>${formatDuration(log.duration)}</td>
                    </tr>`;
                    tableBody.innerHTML += row;
                });
            }
        }

        setInterval(fetchStatus, 2000);
        fetchStatus();
    </script>
</div>
</body>
</html>
"""

def format_duration(seconds):
    if seconds is None:
        return "0:00"
    mins, sec = divmod(int(seconds), 60)
    hrs, mins = divmod(mins, 60)
    return f"{hrs}:{mins:02d}:{sec:02d}" if hrs else f"{mins}:{sec:02d}"

def read_ups_state():
    if TEST_MODE:
        return current_state.copy()
    else:
        return {name: device.value == 1 for name, device in UPS_SIGNALS.items()}

def notify_home_assistant(event):
    try:
        requests.post(WEBHOOKS[event], timeout=5)
        print(f"✅ Webhook for {event}")
    except requests.RequestException as e:
        print(f"❌ Webhook failed for {event}: {e}")

def shutdown_pi():
    print("⚡ Shutdown triggered due to low battery!")
    log_event('low_battery_shutdown', True) 
    os.system('sudo shutdown -h now')

def log_event(event_type, state, duration=None):
    entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "event": event_type,
        "state": "ON" if state else "OFF",
        "duration": duration
    }
    log_buffer.append(entry)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

def get_system_uptime():
    try:
        with open('/proc/uptime', 'r') as f:
            uptime_seconds = float(f.readline().split()[0])
        return uptime_seconds
    except Exception as e:
        print(f"Error reading uptime: {e}")
        return 0

def monitor_inputs():
    global current_state, previous_state, timer_start, shutdown_timer

    while True:
        new_state = read_ups_state()
        with state_lock:
            now = time.time()
            for signal, value in new_state.items():
                prev = previous_state[signal]
                if value != prev:
                    previous_state[signal] = value
                    if value:
                        event_start_times[signal] = now
                        log_event(signal, True)
                        if signal in WEBHOOKS:
                            notify_home_assistant(signal)
                        if signal in timer_start and timer_start[signal] is None:
                            timer_start[signal] = now
                    else:
                        start_time = event_start_times.pop(signal, None)
                        duration = now - start_time if start_time else 0
                        log_event(signal, False, duration)
                        if signal in timer_start and timer_start[signal] is not None:
                            timer_start[signal] = None

                    if signal in ["ups_fault", "alarm", "ups_connected"]:
                        if (not previous_state["ups_connected"]) or previous_state["ups_fault"] or previous_state["alarm"]:
                            ups_fault_led.on()
                        else:
                            ups_fault_led.off()

                    if signal == "low_battery":
                        if value:
                            if shutdown_timer is None:
                                shutdown_timer = threading.Timer(LOW_BATTERY_SHUTDOWN_DELAY, shutdown_pi)
                                shutdown_timer.start()
                                print(f"⚡ Low battery detected! Shutdown scheduled in {LOW_BATTERY_SHUTDOWN_DELAY} seconds...")
                        else:
                            if shutdown_timer is not None:
                                shutdown_timer.cancel()
                                shutdown_timer = None
                                print("⚡ Low battery cleared. Shutdown canceled.")

            current_state = new_state
        time.sleep(1)

@app.route('/')
def index():
    with state_lock:
        state_copy = current_state.copy()
        now = time.time()
        timers = {
            k: format_duration(now - v) if v else "0:00"
            for k, v in timer_start.items()
        }
        recent_logs = list(log_buffer)[-10:]
    return render_template_string(HTML_TEMPLATE, states=state_copy, timers=timers, recent_logs=recent_logs)

@app.route('/logs')
def view_logs():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>All Logs</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <script src="/static/shared.js"></script>
        <style>
            body { background: #111; color: white; text-align: center; font-family: sans-serif; margin: 0; }
            .container { padding: 10px; box-sizing: border-box; }
            table { 
                margin: auto; 
                width: 100%; 
                max-width: 600px; 
                background: #222; 
                border-collapse: collapse; 
                box-sizing: border-box;
            }
            th, td { border: 1px solid #333; padding: 5px; }
            button { margin: 5px; padding: 8px 12px; }
            .indicator {
                width: 15px;
                height: 15px;
                border-radius: 50%;
                display: inline-block;
            }
            .indicator-on { background-color: lime; }
            .indicator-off { background-color: #444; }
            .indicator-fault { background-color: red; }
            .button-row {
                display: flex;
                justify-content: space-between;
                flex-wrap: wrap;
                gap: 12px;
                margin: 0 auto 15px;
                width: 100%;
                max-width: 600px;  /* match the table width */
                box-sizing: border-box;
            }

            .text-button {
                background: none;
                border: none;
                font-size: 16px;
                cursor: pointer;
                padding: 6px 10px;
                color: #0a84ff;  /* iOS blue */
                display: flex;
                align-items: center;
            }

            .text-button:focus {
                outline: none;
            }

            .text-button:hover {
                opacity: 0.7;
            }

            .back-button .chevron {
                font-size: 18px;
                margin-right: 4px;
            }

            .delete-button {
                color: #ff3b30;  /* iOS red */
            }
            .trash-button {
                background: none;
                border: none;
                cursor: pointer;
                padding: 4px;
            }

            .trash-button:focus {
                outline: none;
            }

            .trash-icon {
                width: 20px;
                height: 20px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>All Logs</h1>
            <div class="button-row">
                <button class="text-button back-button" onclick="window.location='/'">
                    <span class="chevron">‹</span> Back
                </button>
                <button class="text-button" onclick="window.location='/api/download_logs'">
                    Download Logs
                </button>
                <button class="text-button delete-button" onclick="deleteAllLogs()">
                    Delete All Logs
                </button>
            </div>
            <table id="all-logs">
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Ago</th>
                        <th>Event</th>
                        <th>State</th>
                        <th>Duration</th>
                        <th>Delete</th>
                    </tr>
                </thead>
                <tbody></tbody>
            </table>
        </div>
        <script>
        async function fetchAllLogs() {
            const res = await fetch('/api/download_logs');
            const text = await res.text();

            const logs = text.trim().split('\\n')
                .filter(line => line.trim().length > 0)
                .map(line => {
                    try {
                        return JSON.parse(line);
                    } catch (err) {
                        console.error('Invalid JSON line:', line, err);
                        return null;
                    }
                })
                .filter(log => log !== null);

            const tbody = document.querySelector('#all-logs tbody');
            tbody.innerHTML = '';
            logs.reverse().forEach((log, index) => {
                tbody.innerHTML += `<tr>
                    <td>${log.timestamp}</td>
                    <td>${timeAgo(log.timestamp)}</td>
                    <td>${formatEventName(log.event)}</td>
                    <td><span class="indicator ${getIndicatorClass(log.event, log.state)}"></span></td>
                    <td>${formatDuration(log.duration)}</td>
                    <td>
                        <button class="trash-button" onclick="deleteLog(${logs.length - index - 1})">
                            <svg xmlns="http://www.w3.org/2000/svg" x="0px" y="0px" width="20" height="20" viewBox="0,0,256,256">
<g fill="#ff0000" fill-rule="nonzero" stroke="none" stroke-width="1" stroke-linecap="butt" stroke-linejoin="miter" stroke-miterlimit="10" stroke-dasharray="" stroke-dashoffset="0" font-family="none" font-weight="none" font-size="none" text-anchor="none" style="mix-blend-mode: normal"><g transform="scale(5.12,5.12)"><path d="M42,5h-10v-2c0,-1.65234 -1.34766,-3 -3,-3h-8c-1.65234,0 -3,1.34766 -3,3v2h-10c-0.55078,0 -1,0.44922 -1,1c0,0.55078 0.44922,1 1,1h1.08594l3.60938,40.51563c0.125,1.39063 1.30859,2.48438 2.69531,2.48438h19.21484c1.38672,0 2.57031,-1.09375 2.69531,-2.48437l3.61328,-40.51562h1.08594c0.55469,0 1,-0.44922 1,-1c0,-0.55078 -0.44531,-1 -1,-1zM20,44c0,0.55469 -0.44922,1 -1,1c-0.55078,0 -1,-0.44531 -1,-1v-33c0,-0.55078 0.44922,-1 1,-1c0.55078,0 1,0.44922 1,1zM20,3c0,-0.55078 0.44922,-1 1,-1h8c0.55078,0 1,0.44922 1,1v2h-10zM26,44c0,0.55469 -0.44922,1 -1,1c-0.55078,0 -1,-0.44531 -1,-1v-33c0,-0.55078 0.44922,-1 1,-1c0.55078,0 1,0.44922 1,1zM32,44c0,0.55469 -0.44531,1 -1,1c-0.55469,0 -1,-0.44531 -1,-1v-33c0,-0.55078 0.44531,-1 1,-1c0.55469,0 1,0.44922 1,1z"></path></g></g>
</svg>
                        </button>
                    </td>
                </tr>`;
            });
        }

        async function deleteLog(index) {
            if (!confirm('Delete this log entry?')) return;
            await fetch('/api/delete_log/' + index, { method: 'POST' });
            fetchAllLogs();
        }

        async function deleteAllLogs() {
            if (!confirm('Delete ALL logs?')) return;
            await fetch('/api/delete_all_logs', { method: 'POST' });
            fetchAllLogs();
        }

        fetchAllLogs();
        </script>
    </body>
    </html>
    """

@app.route('/api/delete_all_logs', methods=['POST'])
def delete_all_logs():
    open(LOG_FILE, 'w').close()  # clear file
    log_buffer.clear()  # clear in-memory buffer
    return jsonify({"success": True})

@app.route('/api/delete_log/<int:index>', methods=['POST'])
def delete_log(index):
    try:
        logs = [json.loads(line) for line in open(LOG_FILE)]
        del logs[index]
        with open(LOG_FILE, 'w') as f:
            for log in logs:
                f.write(json.dumps(log) + '\n')
        log_buffer.clear()
        log_buffer.extend(logs[-100:])
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/status')
def api_status():
    with state_lock:
        status = current_state.copy()
        now = time.time()

        # Calculate battery and low battery durations
        battery_runtime_seconds = int(now - timer_start["on_battery"]) if timer_start["on_battery"] else 0
        low_battery_duration_seconds = int(now - timer_start["low_battery"]) if timer_start["low_battery"] else 0

        # Add both formatted and raw integer durations
        status["battery_runtime"] = format_duration(battery_runtime_seconds)
        status["battery_runtime_seconds"] = battery_runtime_seconds

        status["low_battery_duration"] = format_duration(low_battery_duration_seconds)
        status["low_battery_duration_seconds"] = low_battery_duration_seconds

        uptime_seconds = get_system_uptime()
        status["system_uptime"] = format_duration(uptime_seconds)
        status["system_uptime_seconds"] = int(uptime_seconds)

        status["recent_logs"] = list(log_buffer)[-10:]

    # Flash LED briefly
    network_led.on()
    threading.Timer(0.1, network_led.off).start()  # turn it off after 0.1 second

    return jsonify(status)

@app.route('/api/download_logs')
def api_download_logs():
    return send_file(LOG_FILE, as_attachment=True)

@app.route('/static/<path:filename>')
def static_file(filename):
    return send_from_directory("static", filename)

@app.route('/api/simulate', methods=['POST'])
def simulate():
    data = flask_request.get_json()
    with state_lock:
        for key in data:
            if key in current_state:
                current_state[key] = data[key]
                previous_state[key] = data[key]
    return jsonify({"success": True})

if __name__ == '__main__':
    os.makedirs("static", exist_ok=True)

    # Turn off fault LED (script running OK)
    ups_fault_led.off()

    log_event('monitor_started', True)  

    threading.Thread(target=monitor_inputs, daemon=True).start()
    app.run(host='0.0.0.0', port=80)

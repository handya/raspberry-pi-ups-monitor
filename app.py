from flask import Flask, jsonify, render_template_string, send_from_directory
from gpiozero import DigitalInputDevice
import threading
import requests
import time
import os

app = Flask(__name__)

# GPIO signal mapping
UPS_SIGNALS = {
    "on_ups": DigitalInputDevice(18),
    "on_battery": DigitalInputDevice(17),
    "ups_fault": DigitalInputDevice(27),
    "low_battery": DigitalInputDevice(22),
    "on_bypass": DigitalInputDevice(23),
    "summary_alarm": DigitalInputDevice(24),
}

# Initial state
current_state = {name: False for name in UPS_SIGNALS}
previous_state = current_state.copy()

state_lock = threading.Lock()

WEBHOOKS = {
    "on_battery": "http://<home-assistant-ip>:8123/api/webhook/ups_on_battery",
    "low_battery": "http://<home-assistant-ip>:8123/api/webhook/ups_low_battery",
    "ups_fault": "http://<home-assistant-ip>:8123/api/webhook/ups_fault",
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
    <meta http-equiv="refresh" content="5">
    <style>
        body { font-family: sans-serif; background: #111; color: white; text-align: center; }
        .status { margin-top: 20px; font-size: 18px; }
        .on { fill: lime; stroke: lime; }
        .off { fill: #444; stroke: #444; }
        .flow-line { stroke-width: 3; stroke-dasharray: 6,4; fill: none; }
        svg { margin-top: 40px; }
        .bell {
            position: absolute;
            width: 22px;
            height: 22px;
        }
    </style>
</head>
<body>
    <h1>UPS Status</h1>

    <div id="svg-container" style="position: relative; display: inline-block;">
        <svg width="500" height="300" viewBox="0 0 500 300">
            <rect x="20" y="125" width="60" height="50" class="{{ 'on' if not states['on_battery'] else 'off' }}" />
            <text x="50" y="115" fill="white" text-anchor="middle">Mains</text>

            <rect x="220" y="125" width="60" height="50" class="{{ 'on' if not states['ups_fault'] else 'off' }}" />
            <text x="250" y="115" fill="white" text-anchor="middle">Inverter</text>

            <rect x="420" y="125" width="60" height="50" class="{{ 'on' if states['on_ups'] else 'off' }}" />
            <text x="450" y="115" fill="white" text-anchor="middle">Load</text>

            <rect x="220" y="210" width="60" height="50" class="{{ 'on' if states['on_battery'] else 'off' }}" />
            <text x="250" y="205" fill="white" text-anchor="middle">Battery</text>

            <line x1="80" y1="150" x2="220" y2="150" class="flow-line" stroke="{{ 'lime' if not states['on_battery'] else '#444' }}" />
            <line x1="280" y1="150" x2="420" y2="150" class="flow-line" stroke="{{ 'lime' if states['on_ups'] else '#444' }}" />
            <line x1="250" y1="210" x2="250" y2="175" class="flow-line" stroke="{{ 'lime' if states['on_battery'] else '#444' }}" />
            <path d="M 80 150 Q 250 20, 420 150" class="flow-line" stroke="{{ 'lime' if states['on_bypass'] else '#444' }}" />
        </svg>

        {% if states['on_battery'] %}
            <img id="bell" class="bell" style="top:130px; left:40px;" src="/static/bell0.png">
        {% elif states['ups_fault'] or states['low_battery'] %}
            <img id="bell" class="bell" style="top:130px; left:240px;" src="/static/bell0.png">
        {% endif %}
    </div>

    <div class="status">
        {% for name, active in states.items() %}
            <div>{{ name.replace('_', ' ').title() }}: <b style="color: {{ 'lime' if active else 'gray' }}">{{ 'ON' if active else 'OFF' }}</b></div>
        {% endfor %}
        <div>Battery Runtime: <b>{{ timers['on_battery'] }}</b></div>
        <div>Low Battery Duration: <b>{{ timers['low_battery'] }}</b></div>
    </div>

    <script>
        const bell = document.getElementById('bell');
        if (bell) {
            let frame = 0;
            setInterval(() => {
                frame = (frame + 1) % 8;
                bell.src = `/static/bell${frame}.png`;
            }, 100); // ~10 FPS
        }
    </script>
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
    return {name: device.value == 1 for name, device in UPS_SIGNALS.items()}

def notify_home_assistant(event):
    try:
        requests.post(WEBHOOKS[event], timeout=5)
        print(f"✅ Webhook for {event}")
    except requests.RequestException as e:
        print(f"❌ Webhook failed for {event}: {e}")

def monitor_inputs():
    global current_state, previous_state, timer_start

    while True:
        new_state = read_ups_state()
        with state_lock:
            for signal, value in new_state.items():
                prev = previous_state[signal]
                if value != prev:
                    previous_state[signal] = value
                    if value and signal in WEBHOOKS:
                        notify_home_assistant(signal)
                    if signal in timer_start:
                        if value and timer_start[signal] is None:
                            timer_start[signal] = time.time()
                        elif not value and timer_start[signal] is not None:
                            timer_start[signal] = None
            current_state = new_state
        time.sleep(1)

@app.route('/')
def index():
    with state_lock:
        state_copy = current_state.copy()
        timers = {
            k: format_duration(time.time() - v) if v else "0:00"
            for k, v in timer_start.items()
        }
    return render_template_string(HTML_TEMPLATE, states=state_copy, timers=timers)

@app.route('/api/status')
def api_status():
    with state_lock:
        status = current_state.copy()
        status["battery_runtime"] = format_duration(time.time() - timer_start["on_battery"]) if timer_start["on_battery"] else "0:00"
        status["low_battery_duration"] = format_duration(time.time() - timer_start["low_battery"]) if timer_start["low_battery"] else "0:00"
    return jsonify(status)

@app.route('/static/<path:filename>')
def static_file(filename):
    return send_from_directory("static", filename)

if __name__ == '__main__':
    os.makedirs("static", exist_ok=True)
    threading.Thread(target=monitor_inputs, daemon=True).start()
    app.run(host='0.0.0.0', port=80)

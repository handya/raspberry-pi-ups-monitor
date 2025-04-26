from flask import Flask, jsonify, render_template_string, send_from_directory, request as flask_request
from gpiozero import DigitalInputDevice
import threading
import requests
import time
import os

TEST_MODE = False
LOW_BATTERY_SHUTDOWN_DELAY = 30  # seconds
shutdown_timer = None

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
    <style>
        body { font-family: sans-serif; background: #111; color: white; text-align: center; }
        .status { margin-top: 20px; font-size: 18px; }
        .error { color: red; font-weight: bold; margin-top: 10px; }
        .on { fill: lime; stroke: lime; }
        .off { fill: #444; stroke: #444; }
        .flow-line { stroke-width: 3; stroke-dasharray: 6,4; fill: none; }
        svg { margin-top: 40px; }
        .bell {
            position: absolute;
            width: 30px;
            height: 30px;
            background-image: url('/static/bell-sprite.png');
            background-repeat: no-repeat;
            background-size: 240px 30px; /* 8 frames × 30px */
            display: none;
        }
    </style>
</head>
<body>
    <h1>UPS Status</h1>

    <div id="svg-container" style="position: relative; display: inline-block;">
        <svg id="ups-diagram" width="500" height="300" viewBox="0 0 500 300">
            <rect id="mains" x="20" y="125" width="60" height="50" />
            <text x="50" y="115" fill="white" text-anchor="middle">Mains</text>

            <rect id="inverter" x="220" y="125" width="60" height="50" />
            <text x="250" y="115" fill="white" text-anchor="middle">Inverter</text>

            <rect id="load" x="420" y="125" width="60" height="50" />
            <text x="450" y="115" fill="white" text-anchor="middle">Load</text>

            <rect id="battery" x="220" y="210" width="60" height="50" />
            <text x="250" y="205" fill="white" text-anchor="middle">Battery</text>

            <line id="mains-inverter" x1="80" y1="150" x2="220" y2="150" class="flow-line" />
            <line id="inverter-load" x1="280" y1="150" x2="420" y2="150" class="flow-line" />
            <line id="battery-inverter" x1="250" y1="210" x2="250" y2="175" class="flow-line" />
            <path id="bypass-line" d="M 80 150 Q 250 20, 420 150" class="flow-line" />
        </svg>

        <div id="bell-mains" class="bell"></div>
        <div id="bell-inverter" class="bell"></div>
        <div id="bell-battery" class="bell"></div>
    </div>

    <div class="status" id="status-text">
        Loading...
    </div>
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

            document.getElementById('mains-inverter').setAttribute('stroke', states.on_battery ? '#444' : 'lime');
            document.getElementById('inverter-load').setAttribute('stroke', states.on_ups ? 'lime' : '#444');
            document.getElementById('battery-inverter').setAttribute('stroke', states.on_battery ? 'lime' : '#444');
            document.getElementById('bypass-line').setAttribute('stroke', states.on_bypass ? 'lime' : '#444');

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
                <div>On UPS: <b style="color:${states.on_ups ? 'lime' : 'gray'}">${states.on_ups ? 'ON' : 'OFF'}</b></div>
                <div>On Battery: <b style="color:${states.on_battery ? 'lime' : 'gray'}">${states.on_battery ? 'ON' : 'OFF'}</b></div>
                <div>UPS Fault: <b style="color:${states.ups_fault ? 'red' : 'gray'}">${states.ups_fault ? 'ON' : 'OFF'}</b></div>
                <div>Low Battery: <b style="color:${states.low_battery ? 'red' : 'gray'}">${states.low_battery ? 'ON' : 'OFF'}</b></div>
                <div>On Bypass: <b style="color:${states.on_bypass ? 'red' : 'gray'}">${states.on_bypass ? 'ON' : 'OFF'}</b></div>
                <div>Alarm: <b style="color:${states.summary_alarm ? 'red' : 'gray'}">${states.summary_alarm ? 'ON' : 'OFF'}</b></div>
                <div>Battery Runtime: <b>${states.battery_runtime}</b></div>
                <div>Low Battery Duration: <b>${states.low_battery_duration}</b></div>
            `;
            document.getElementById('status-text').innerHTML = statusText;
        }

        setInterval(fetchStatus, 2000);
        fetchStatus();
    </script>
</body>
</html>
"""

# -- Rest of the Python server code below remains identical --

# (continued below if needed — do you want me to post full continuation too?)


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
    os.system('sudo shutdown -h now')

def monitor_inputs():
    global current_state, previous_state, timer_start, shutdown_timer

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

                    # Handle low battery shutdown
                    if signal == "low_battery":
                        if value:  # low_battery turned ON
                            if shutdown_timer is None:
                                shutdown_timer = threading.Timer(LOW_BATTERY_SHUTDOWN_DELAY, shutdown_pi)
                                shutdown_timer.start()
                                print(f"⚡ Low battery detected! Shutdown scheduled in {LOW_BATTERY_SHUTDOWN_DELAY} seconds...")
                        else:  # low_battery turned OFF
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
    threading.Thread(target=monitor_inputs, daemon=True).start()
    app.run(host='0.0.0.0', port=80)

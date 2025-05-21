from flask import Flask, jsonify, render_template, send_file, send_from_directory, request as flask_request, Response
from gpiozero import DigitalInputDevice
from collections import deque
import threading
import requests
import time
import os
from gpiozero import LED
import json
import tempfile

TEST_MODE = False
LOW_BATTERY_SHUTDOWN_DELAY = 30  # seconds
shutdown_timer = None

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(BASE_DIR, 'settings.json')
LOG_FILE = os.path.join(BASE_DIR, 'log.jsonl')

log_buffer = deque(maxlen=1000)
event_start_times = {}
settings = {}

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

REVERSED_INPUTS = {
    "on_ups",
    "on_battery",
    "ups_fault",
    "low_battery",
    "on_bypass",
    "alarm"
}

# Initial state
current_state = {name: False for name in UPS_SIGNALS}
previous_state = current_state.copy()

state_lock = threading.Lock()

timer_start = {
    "on_battery": None,
    "low_battery": None,
}

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
        return {
            name: (device.value == 0 if name in REVERSED_INPUTS else device.value == 1)
            for name, device in UPS_SIGNALS.items()
        }

def send_webhook(event):
    webhook_url = settings.get('webhooks', {}).get(event)

    if not webhook_url:
        print(f"⚠️ Skipping webhook for {event} (no URL set)")
        return

    try:
        requests.post(webhook_url, timeout=5)
        print(f"✅ Webhook sent for {event}")
    except requests.RequestException as e:
        print(f"❌ Webhook failed for {event}: {e}")

def shutdown_pi():
    print("⚡ Shutdown triggered due to low battery!")
    log_event('low_battery_shutdown', True) 
    os.system('sudo shutdown -h now')

def load_settings():
    global settings
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE) as f:
            settings = json.load(f)
    else:
        settings = {}

def log_event(event_type, state, duration=None):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    entry = {
        "timestamp": timestamp,
        "event": event_type,
        "state": "ON" if state else "OFF",
        "duration": None
    }

    # Patch in-memory buffer if needed
    if duration is not None:
        for past_entry in reversed(log_buffer):
            if past_entry["event"] == event_type:
                past_entry["duration"] = duration
                break

    # Add current event to buffer
    log_buffer.append(entry)

    # Write entire buffer to file
    with open(LOG_FILE, 'w') as f:
        for log in log_buffer:
            f.write(json.dumps(log) + '\n')

def get_system_uptime():
    try:
        with open('/proc/uptime', 'r') as f:
            uptime_seconds = float(f.readline().split()[0])
        return uptime_seconds
    except Exception as e:
        print(f"Error reading uptime: {e}")
        return 0

REVERSE_TIMER_SIGNALS = {"on_ups", "ups_connected"}

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

                    if signal in REVERSE_TIMER_SIGNALS:
                        # these are “good when ON” → flip logic
                        if not value:
                            event_start_times[signal] = now
                            log_event(signal, False)
                        else:
                            start_time = event_start_times.pop(signal, None)
                            duration = now - start_time if start_time else 0
                            log_event(signal, True, duration)
                    else:
                        if value:
                            event_start_times[signal] = now
                            log_event(signal, True)
                            if signal in settings.get('webhooks', {}):
                                send_webhook(signal)
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
    return render_template('index.html', states=state_copy, timers=timers, recent_logs=recent_logs, settings=settings)

@app.route('/logs')
def view_logs():
    return render_template('logs.html')

@app.route('/settings')
def settings_page():
    return render_template('settings.html', settings=settings)

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

@app.route('/api/shutdown', methods=['POST'])
def shutdown():
    log_event('manual_shutdown', True)  
    os.system('sudo shutdown -h now')
    return '', 204

@app.route('/api/reboot', methods=['POST'])
def reboot():
    log_event('manual_reboot', True)  
    os.system('sudo reboot')
    return '', 204

@app.route('/api/save_settings', methods=['POST'])
def save_settings():
    global settings
    data = flask_request.get_json()

    # Update ups_name
    settings['ups_name'] = data.get('ups_name', '')

    # Update ups_type
    settings['ups_type'] = data.get('ups_type', '')

    # Ensure webhooks section exists
    if 'webhooks' not in settings:
        settings['webhooks'] = {}

    # Process webhooks: save as null if empty string
    for key in ['on_battery', 'low_battery', 'ups_fault']:
        value = data['webhooks'].get(key)
        settings['webhooks'][key] = value if value.strip() else None

    # Save to file
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)

    log_event('settings_updated', True)

    return '', 204

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

@app.route('/api/logs')
def api_logs():
    event_filter = flask_request.args.get('event')
    logs = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    if event_filter and entry['event'] != event_filter:
                        continue
                    logs.append(entry)
                except json.JSONDecodeError:
                    continue
    return jsonify(logs)

@app.route('/api/download/logs.json')
def api_download_logs():
    event_filter = flask_request.args.get('event')  # get ?event= from query

    if not os.path.exists(LOG_FILE):
        return Response("[]", mimetype='application/json')

    with open(LOG_FILE, 'r') as f:
        logs = [json.loads(line) for line in f if line.strip()]

    # Apply filter if ?event= provided
    if event_filter:
        logs = [log for log in logs if log.get('event') == event_filter]

    # Write filtered logs to a temporary .json file
    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as tmp:
        json.dump(logs, tmp, indent=2)
        tmp_path = tmp.name

    # Send the file for download
    return send_file(tmp_path, as_attachment=True, download_name='logs.json', mimetype='application/json')


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

    load_settings()

    # Turn off fault LED (script running OK)
    ups_fault_led.off()

    log_event('monitor_started', True)  

    threading.Thread(target=monitor_inputs, daemon=True).start()
    app.run(host='0.0.0.0', port=80)

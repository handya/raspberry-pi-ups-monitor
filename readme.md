# UPS Monitor for Raspberry Pi

A lightweight Flask web app to monitor UPS relay signals from a Vertiv IntelliSlot® Relay Card connected to a Raspberry Pi GPIO.

The app provides:
- A live SVG schematic showing UPS status (Mains, Inverter, Battery, Load).
- Animated bell icons for alarms (On Battery, UPS Fault, Low Battery).
- API for external integrations (JSON status endpoint).
- Home Assistant webhook notifications.
- Automatic shutdown on low battery after a configurable delay.

---

## Features

- Realtime web dashboard (auto-updates every 2 seconds).
- Smooth animated status indicators.
- Error message display if the Pi or server becomes unreachable.
- Clean shutdown triggered after `LOW_BATTERY_SHUTDOWN_DELAY`.
- Designed for very low resource usage (perfect for old Raspberry Pi models).

---

## Hardware Requirements

- Raspberry Pi (any model with GPIO, tested on original Pi B).
- Vertiv IntelliSlot® Relay Card connected to GPIO inputs.
- Internet or LAN access (for web UI).

---

## Installation

1. **Update your Pi:**

```bash
sudo apt update
sudo apt upgrade
```

2. **Install Python dependencies:**

```bash
sudo apt install python3-pip
pip3 install flask gpiozero requests
```

3. **Clone or copy this repository into your Pi:**

```bash
git clone https://github.com/handya/raspberry-pi-ups-monitor.git
cd ups-monitor
```

(Or manually upload your files if you prefer.)

4. **Check your wiring:**

Connect your UPS relay outputs to the correct GPIO pins:
- `On UPS` → GPIO 18
- `On Battery` → GPIO 17
- `UPS Fault` → GPIO 27
- `Low Battery` → GPIO 22
- `On Bypass` → GPIO 23
- `Summary Alarm` → GPIO 24

Adjust GPIO pins in the script if needed.

---

## Running the App

From the `raspberry-pi-ups-monitor` folder:

```bash
sudo python3 scripts/ups-monitor.py
```

Visit the Pi's IP address in your browser:

```
http://<pi-ip-address>/
```

You should see the UPS monitor dashboard!

---

## Setting it up to Run on Boot

1. **Create a systemd service:**

```bash
sudo nano /etc/systemd/system/ups-monitor.service
```

Paste this:

```ini
[Unit]
Description=UPS Monitor Web App
After=network.target

[Service]
WorkingDirectory=/home/pi/
ExecStart=/usr/bin/python3 scripts/ups-monitor.py
Restart=always
User=root
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

(Adjust paths if needed.)

2. **Enable and start it:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable ups-monitor
sudo systemctl start ups-monitor
```

✅ It will now automatically start after reboot.

---

## Config Options

Edit the top of `ups-monitor.py` to configure:

```python
TEST_MODE = False          # Set to True to simulate GPIO signals
LOW_BATTERY_SHUTDOWN_DELAY = 30  # Delay in seconds before shutdown on low battery
```

---

## API Endpoints

- `GET /api/status` → JSON object with current UPS status.
- `POST /api/simulate` → Simulate GPIO inputs for testing (only when TEST_MODE=True).

---

## Home Assistant Integration

Webhooks are automatically triggered on:
- On Battery
- Low Battery
- UPS Fault

Webhook URLs are configured inside `WEBHOOKS` in `ups-monitor.py`.

---

## License

MIT License

---

## Notes

- This project is optimized for reliability and speed — no databases, no heavy frameworks.
- If you lose connection to the Pi, the webpage will automatically display an error until connection is restored.
- Designed to be simple, fast, and highly reliable for home servers and network UPS monitoring.

---
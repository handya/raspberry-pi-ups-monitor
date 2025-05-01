# UPS Monitor for Raspberry Pi

A lightweight Flask web app to monitor UPS relay signals from a Vertiv IntelliSlot® Relay Card connected to a Raspberry Pi GPIO.

Created as part of this YouTube Video, feedback and pull requests welcome.
[https://youtu.be/_P4-Sfet08s](https://youtu.be/_P4-Sfet08s)

The app provides:
- A live SVG schematic showing UPS status (Mains, Inverter, Battery, Load).
- Animated bell icons for alarms (On Battery, UPS Fault, Low Battery).
- API for external integrations (JSON status endpoint + logs).
- Home Assistant webhook notifications.
- Automatic shutdown on low battery after a configurable delay.
- Web-based settings page to configure UPS name and webhook URLs.
- Simple log viewing, downloading, filtering, and deletion via the web UI.

---

## Features

✅ Realtime web dashboard (auto-updates every 2 seconds)  
✅ Animated status indicators + error overlay  
✅ Log viewer with delete and download options  
✅ Settings page to set UPS name + webhook URLs  
✅ REST API for external automation  
✅ Home Assistant webhooks (configurable in UI)  
✅ Automatic clean shutdown on low battery  
✅ Lightweight footprint, perfect for old Raspberry Pis

---

## Hardware Requirements

- Raspberry Pi (any model with GPIO; tested on original Pi B)
- Vertiv IntelliSlot® Relay Card connected to GPIO inputs
- LAN or Wi-Fi access (for web UI + API)

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

3. **Clone this repository:**

```bash
git clone https://github.com/handya/raspberry-pi-ups-monitor.git
cd raspberry-pi-ups-monitor
```

4. **Check your GPIO wiring:**

Connect these relay outputs:
- `On UPS` → GPIO 18
- `On Battery` → GPIO 17
- `UPS Fault` → GPIO 27
- `Low Battery` → GPIO 22
- `On Bypass` → GPIO 23
- `Alarm` → GPIO 24

Adjust GPIO pins in the script if needed.

---

## Running the App

```bash
sudo python3 scripts/ups-monitor.py
```

Open in your browser:

```
http://<pi-ip-address>/
```

---

## Auto-Start on Boot

1. **Create a systemd service:**

```bash
sudo nano /etc/systemd/system/ups-monitor.service
```

Paste:

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

2. **Enable + start it:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable ups-monitor
sudo systemctl start ups-monitor
```

---

## Config Options

Config is stored in **`settings.json`**:

```json
{
  "ups_name": "Network UPS",
  "webhooks": {
    "on_battery": null,
    "low_battery": null,
    "ups_fault": null
  }
}
```

Update settings via the **web-based settings page** (`/settings`) — no need to edit the file manually.

---

## Home Assistant Webhooks

Webhooks notify when:
- **UPS on battery**
- **Low battery**
- **UPS fault**

Set webhook URLs on `/settings` page:
- Example:
  ```
  http://<home-assistant-ip>:8123/api/webhook/ups_on_battery
  ```

Make sure webhooks are set up in Home Assistant.

---

## API Endpoints

- `GET /api/status` → current UPS state + recent logs  
- `GET /api/download/logs.json` → download logs (as `.json` or filter with `?event=on_battery`)  
- `POST /api/simulate` → simulate GPIO inputs (when TEST_MODE=True)  
- `POST /api/shutdown` → shutdown the Pi  
- `POST /api/reboot` → reboot the Pi  
- `POST /api/set_settings` → update all settings

---

## Logs Page

- See recent + all logs (`/logs`)
- Filter by event in the API (`/api/download/logs.json?event=on_battery`)
- Delete individual logs or clear all logs

---

## Template and Static Files

All HTML templates are now stored in:
```
/templates/
    index.html
    settings.html
    logs.html
```

CSS, JavaScript, and icons can be placed in:
```
/static/
```

---

## Notes

- Minimal resource usage (~20–30 MB RAM)
- Resilient to disconnections (UI auto-reconnects)
- Designed for 24/7 headless operation

---

## License

MIT License
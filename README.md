# Auto Aqua Smart Doser - Home Assistant Integration

A custom [Home Assistant](https://www.home-assistant.io/) integration for the **Auto Aqua Smart Doser 4** aquarium dosing pump, installed via [HACS](https://hacs.xyz/).

> **Supported devices:** Only the **Smart Doser 4** is supported at this time.

## Features

- **Cloud API** — Connects to the Auto Aqua Aqualine cloud service using your account credentials
- **4 Pump control** — Independent dose amount and trigger for each pump
- **Sensors** — Device online status, firmware version, tank name
- **Service call** — `autoaqua_doser.dose` for use in HA automations and scripts
- **60-second polling** — Automatic device status updates

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations** → **Custom repositories**
3. Add this repository URL: `https://github.com/pazhanir/autoaqua-smart-doser-ha`
4. Category: **Integration**
5. Click **Download**
6. Restart Home Assistant

### Manual

1. Copy the `custom_components/autoaqua_doser` folder into your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Setup

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **Auto Aqua Smart Doser**
3. Enter your Auto Aqua (Aqualine app) email and password
4. Your doser will be auto-discovered

## Entities

| Entity | Type | Description |
|---|---|---|
| Status | Sensor | Online / Offline |
| Firmware | Sensor | Firmware version |
| Tank | Sensor | Associated tank name |
| Pump 1-4 Dose Amount | Number | Set dose amount (1-999 ml) |
| Pump 1-4 Dose | Button | Press to trigger dose at the set amount |

## Service: `autoaqua_doser.dose`

Trigger a dose from an automation or script:

```yaml
service: autoaqua_doser.dose
data:
  device_id: "34B7DA28DE69"
  pump: 1
  ml: 5
```

| Parameter | Required | Description |
|---|---|---|
| `device_id` | Yes | Device MAC / ID |
| `pump` | Yes | Pump number (1-4) |
| `ml` | Yes | Milliliters to dose (1-999) |

### Example automation

```yaml
automation:
  - alias: "Morning dose - Pump 1"
    trigger:
      - platform: time
        at: "08:00:00"
    action:
      - service: autoaqua_doser.dose
        data:
          device_id: "34B7DA28DE69"
          pump: 1
          ml: 5
```

## Hardware Notes

- Only **one pump can dose at a time** — do not trigger parallel doses
- Dose amounts are **integer ml only** (no fractions)
- Maximum **999 ml** per dose per pump
- Scheduling is handled via HA automations, not device-level schedules

## License

MIT

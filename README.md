<p align="center">
  <img src="logo.png" alt="Smart Area Logo" width="150" />
</p>

# Smart Area for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Maintainer](https://img.shields.io/badge/maintainer-noem--9C9-blue)](https://github.com/noem-9C9)

**Smart Area** is an advanced custom integration for Home Assistant that intelligently aggregates your entities based on Home Assistant **Areas** and **Labels**. It provides four kinds of virtual entities:

- **Light groups** — per area and/or house-wide, solving the limitations of the native "Light Group" platform.
- **Cover groups** — per area and/or house-wide (e.g. one entity for all the living-room shutters).
- **Switch groups** — per area and/or house-wide.
- **Global average sensors** — one house-wide entity per sensor type (temperature, humidity, ...), with optional per-sensor offsets.

## ✨ Features

### Common to all groups
- 🏠 **Area-Based Auto-Grouping**: Select Areas (or all of them), and each one gets its own group entity. New devices added to the room join the group automatically.
- 🌍 **House-Wide Scope**: Optionally create one global entity covering the whole house — per area, globally, or both at once.
- 🏷️ **Label Filtering**: Restrict a group to entities whose entity **or parent device** carries a given label.
- ⚡ **Dynamic Discovery Ready**: Automatically detects when Zigbee2MQTT or ZHA finishes loading devices after startup.

### 💡 Light groups
- 🧠 **Clean Capability Mixing**: The group exposes a canonical set of color modes (ON/OFF, Brightness, Color Temperature, RGB) computed from its members; Home Assistant converts colors to each bulb's native mode (HS, XY, RGBW, ...) automatically.
- 🌙 **Smart Dimming**: If the group is partially on, adjusting brightness/color only affects the bulbs that are already lit, keeping the others off.
- 📊 **Honest Averages**: Color temperature is averaged only over bulbs currently in color-temp mode, RGB only over bulbs currently in a color mode.

### 🪟 Cover groups
- Open / close / stop and **average position** (forwarded only to covers that support each feature).
- The group is *closed* only when **all** members are closed, and reports opening/closing states.

### 🔌 Switch groups
- The group is *on* if **any** member is on; turning it on/off drives all members.

### 🌡️ Global average sensors
- 🏠 **House-Wide Averages**: Type a list of keywords (e.g., `temperature, humidite`) and get one global entity per keyword (e.g., `sensor.global_avg_temperature`) averaging every matching sensor in the house.
- 🔎 **Flexible Matching**: A sensor matches a keyword if its entity id, name or device class contains it (accent-insensitive, so `humidite` matches `Humidité Salon`).
- 🎚️ **Per-Sensor Offsets**: Calibrate any source sensor after the fact via the Configure dialog — one line per sensor, e.g. `sensor.temp_salon = -0.5`.
- 🛡️ **Unit-Safe Averaging**: Values are grouped by unit of measurement and only the majority group is averaged, so a mismatched sensor can't corrupt the result. `min`/`max`, applied offsets and the tracked entities are exposed as attributes.

## 📥 Installation

### HACS (Recommended)
1. Open HACS in Home Assistant.
2. Click the three dots in the top right corner and select **Custom repositories**.
3. Add the URL of this repository: `https://github.com/noem-9C9/smart-area`
4. Select category: **Integration**.
5. Click **Add**, then search for "Smart Area" and click Download.
6. Restart Home Assistant.

### Manual Installation
1. Download the `smart_area` folder from this repository.
2. Copy it into your `custom_components/` directory in Home Assistant.
3. Restart Home Assistant.

> **Upgrading from `smart_area_lights` (v2.x)?** The domain has been renamed to `smart_area`: remove the old integration entries and the old `smart_area_lights` folder, then add the integration again.

## ⚙️ Configuration

This integration supports **Config Flow** (Setup via the UI).

1. Go to **Settings** > **Devices & Services**.
2. Click **+ Add Integration** in the bottom right corner.
3. Search for **Smart Area**.
4. Choose what to create:
   - **Light / Cover / Switch groups**: select the target Areas and/or tick "house-wide global entity", optionally filter by Label. One entity is created per area (e.g., `light.group_auto_living_room`) plus, if requested, a global one (e.g., `cover.group_auto_home`).
   - **Global sensors**: enter the keywords (comma-separated), optionally filter by Label. One Sensor entity is created per keyword (e.g., `sensor.global_avg_temperature`).

All settings (areas, global entity, labels, light capabilities, sensor keywords and offsets) can be changed at any time via the integration's **Configure** button — entities are reloaded automatically.

## 🖼️ Logo in the Home Assistant UI

The icons shown on the *Devices & Services* page are served from [home-assistant/brands](https://github.com/home-assistant/brands), not from this repository. Ready-to-submit assets are provided in [`brands/smart_area/`](brands/smart_area/) (`icon.png` 256×256, `icon@2x.png` 512×512): open a PR adding that folder under `custom_integrations/smart_area/` to get the logo displayed in HA. HACS and the README use `logo.png` directly.

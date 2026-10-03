# Independent LCD Engine – SignalRGB Add-on

Add-on package layout for **Settings → Add-ons**. This repository integration is a Network/Discovery service, not a USB device plugin, so the service controller can appear under SignalRGB's Third Party Services area.

## Components

- `SignalRGB_LCD_Engine.js` — SignalRGB network add-on and local service discovery/controller.
- `SignalRGB_LCD_Engine.qml` — settings page for discovery state and linked LCD service.
- `service/lcd_engine_service.py` — local helper. It detects the LCD over HID, renders independent faces, and sends frames directly to the screen.

The helper is separate because the SignalRGB Network/Discovery add-on does not itself claim a USB HID endpoint. It communicates with the helper through loopback UDP. The renderer and transport do not call `@SignalRGB/lcd`.

## Install through SignalRGB Add-ons

SignalRGB's Add-ons page accepts a repository URL. This folder must first be published as a Git repository (GitLab or another supported Git host); then add that repository URL at **Settings → Add-ons → Add** and restart SignalRGB if prompted. A local folder path is not a repository URL.

Start the helper with Python before launching the add-on:

```powershell
python -m pip install -r service/requirements.txt
python service/lcd_engine_service.py
```

The helper must eventually be packaged/installed as a background Windows service for automatic startup. The current source version is foreground/manual and intended for integration development.

## Current state and constraints

- The service plug-in uses SignalRGB's `Type() { return "network"; }` and `DiscoveryService()` pattern used by existing SignalRGB add-ons.
- The local HID protocol is adapted from the named `Thermalright_Frozen_Warframe_0416_5302.js` source; `@SignalRGB/lcd` frame acquisition was removed. VID/PID, usage page, usage, packet envelope, RGB565 format, and handshake remain specific to that source's device.
- This is not a general driver for arbitrary LCD hardware. Extending it to other LCDs requires additional protocol adapters.
- SignalRGB's public docs explain adding third-party devices and USB plugins, but the DiscoveryService add-on contract is not comprehensively documented. Validate it against the installed SignalRGB release.
- This source package has not been tested against the physical LCD or installed in SignalRGB.

## Files

Add-on files live at repository root so SignalRGB's Add-ons loader can find the JS and QML by name.

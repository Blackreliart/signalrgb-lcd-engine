# Independent LCD Engine — SignalRGB Add-on

The SignalRGB integration is a Network/Discovery service shown under **Third Party Services**. A local Python helper owns USB/HID rendering and serves the visual editor at `http://127.0.0.1:41722/`.

## Editor features

- Responsive preview and automatic widget-coordinate scaling when switching portrait/landscape rotation
- Rotation: 0°, 90°, 180°, or 270°; safe margins and global font scaling
- Drag, add, remove, position, show/hide, recolor and resize up to 12 widgets
- Widgets: title, clock, date, CPU/RAM values and bars, computer name, uptime, and custom text
- Background: solid color, directional two-color gradient, uploaded image, or sampled SignalRGB effect
- Image fit (cover/contain/stretch), background dimming, brightness, and 1–15 FPS

Click **LCD Editor öffnen** in the add-on page or visit the local editor URL while the helper is running. The SignalRGB effect capture toggle is in the editor under **Hintergrund → SignalRGB-Effekt erfassen**; it is not a SignalRGB add-on control. The helper reflects that toggle to the SignalRGB service through its discovery response. When enabled, the add-on samples a 16×20 grid from `device.color(x,y)` at up to 8 FPS. It is a low-bandwidth color sample, not a full-resolution LCD frame.

The editor stores configuration at `%LOCALAPPDATA%\\IndependentLCDEngine\\config.json`. The editor only binds to loopback (`127.0.0.1`).

## Start the helper

From the local repository root:

```powershell
python -m pip install -r service/requirements.txt
python service/lcd_engine_service.py
```

Keep it running. Push the updated repository files to GitHub and reload the add-on in SignalRGB. Restart the Python helper after replacing local helper files.

## Files and limits

- `SignalRGB_LCD_Engine.js` — Network/Discovery integration and optional SignalRGB canvas sampler.
- `SignalRGB_LCD_Engine.qml` — add-on page with editor launch button.
- `service/editor.html` — visual editor.
- `service/lcd_engine_service.py` — editor API, renderer and HID transport.
- `service/requirements.txt` — `hidapi`, Pillow and psutil.

The HID protocol adapter is specific to reference device `VID:PID 0416:5302`; it is not a universal LCD driver. The live effect preview in the editor is illustrative; the LCD renders the actual sampled grid after capture is enabled.

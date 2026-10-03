# Independent LCD Engine — SignalRGB Add-on

The SignalRGB integration is a Network/Discovery service shown under **Third Party Services**. A local Python helper owns USB/HID rendering and serves the visual editor at `http://127.0.0.1:41722/`.

## Editor features

- Responsive preview and automatic widget-coordinate scaling when switching portrait/landscape rotation
- Rotation: 0°, 90°, 180°, or 270°; safe margins and global font scaling
- Drag, add, remove, position, show/hide, recolor and resize up to 12 widgets
- Widgets: title, clock, date, CPU/RAM values and bars, computer name, uptime, and custom text
- Background: solid color, directional two-color gradient, uploaded image, or sampled SignalRGB effect
- Image fit (cover/contain/stretch), background dimming, brightness, and 1–15 FPS

SignalRGB canvas capture is unavailable in this Third Party Service: SignalRGB does not provide the device-plugin `device.color()` object in this service context. The UI marks the option as unavailable instead of pretending frames are being captured. Canvas sampling would require a separate device plugin, which would be listed as a device rather than under Third Party Services.

GPU widgets are available in the editor for utilization, temperature, memory, and a utilization bar. The helper reads all four metrics from `nvidia-smi` when present. Without NVIDIA tools it falls back to the Windows WDDM 3D utilization counter; temperature and VRAM then display as unavailable. GPU polling runs every two seconds.

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

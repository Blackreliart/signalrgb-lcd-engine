# Independent LCD Engine — SignalRGB Add-on

The SignalRGB integration is a Network/Discovery service shown under **Third Party Services**. The Thermalright device plugin remains the only HID owner. It samples the LCD frame and exchanges effect samples/rendered frames with the local Python helper over loopback UDP. The helper serves the visual editor at `http://127.0.0.1:41722/`.

## Editor features

- Responsive preview and automatic widget-coordinate scaling when switching portrait/landscape rotation
- Rotation: 0°, 90°, 180°, or 270°; safe margins and global font scaling
- Drag, add, remove, position, show/hide, recolor and resize up to 12 widgets
- Widgets: title, clock, date, CPU/RAM values and bars, computer name, uptime, and custom text
- Background: solid color, directional two-color gradient, uploaded image, or sampled SignalRGB effect
- Image fit (cover/contain/stretch), background dimming, brightness, and 1–15 FPS

SignalRGB does not expose `device.color()` to a Third Party Service. The included `Thermalright_Frozen_Warframe_LCD_Bridge.js` therefore uses the existing device plugin's `LCD.getFrame()` source, sends a 16×20 sample to the helper at 8 FPS, and writes helper-rendered frames back to the LCD. The add-on's capture switch controls whether the helper uses that sample as its background. The Thermalright plugin must remain enabled in SignalRGB; do not run another process that opens the LCD HID interface.

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

- `SignalRGB_LCD_Engine.js` — Network/Discovery integration for Third Party Services.
- `SignalRGB_LCD_Engine.qml` — add-on page with editor launch button.
- `Thermalright_Frozen_Warframe_LCD_Bridge.js` — bridge replacement for the user's existing Thermalright device plugin.
- `service/editor.html` — visual editor.
- `service/lcd_engine_service.py` — editor API, renderer and UDP frame bridge; it does not open HID.
- `service/requirements.txt` — Pillow and psutil.

The bridge plugin and frame protocol target the reference device `VID:PID 0416:5302`; they are not a universal LCD driver. The editor preview is illustrative; the LCD shows the helper's output when the SignalRGB capture option or another configured background is active.

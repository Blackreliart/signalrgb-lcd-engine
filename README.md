# Independent LCD Engine — SignalRGB Add-on

Dieses Add-on erscheint als Network/Discovery-Service unter **Third Party Services**. Das Add-on übergibt Einstellungen an den lokalen Renderer; der Renderer liest CPU/RAM aus Windows und sendet geänderte RGB565-Bilder mit niedriger Bildrate an das LCD.

## Anpassungen in SignalRGB

Öffne **Third Party Services → Independent LCD Engine → Einstellungen**. Dort kannst du einstellen:

- Anzeige: Dashboard, Uhr, Systembalken oder Testbild
- eigene Überschrift und 12-/24-Stunden-Uhr
- Uhr, CPU und RAM einzeln ein- und ausblenden
- Akzent- und Hintergrundfarbe
- Helligkeit und Bildrate (1–15 FPS)

Die Werte werden vom lokalen Renderer übernommen. CPU/RAM werden über psutil höchstens einmal pro Sekunde gelesen; HID-Bilder werden nur übertragen, wenn sich das Bild geändert hat.

## Einrichtung

Das Add-on-Repository wird in SignalRGB unter **Settings → Add-ons** hinzugefügt. Der lokale Hilfsdienst muss separat gestartet werden:

```powershell
python -m pip install -r service/requirements.txt
python service/lcd_engine_service.py
```

Nach Änderungen am Add-on muss die aktualisierte Version ins GitHub-Repository gepusht und in SignalRGB neu geladen werden. Nach Änderungen am Python-Helfer muss dessen lokale Datei ersetzt und der Prozess neu gestartet werden.

## Dateien

- `SignalRGB_LCD_Engine.js` — SignalRGB-Service und anpassbare Controls.
- `SignalRGB_LCD_Engine.qml` — Beschreibung/Hinweis im Add-on.
- `service/lcd_engine_service.py` — Layouts, Systemwerte und HID-Transport.
- `service/requirements.txt` — Python-Abhängigkeiten (`hidapi`, Pillow, psutil).

Der HID-Adapter verwendet das Protokoll aus der Thermalright-Referenz (VID/PID `0416:5302`). Er ist nicht generisch für andere LCDs. Der lokale Dienst muss während der Nutzung laufen.

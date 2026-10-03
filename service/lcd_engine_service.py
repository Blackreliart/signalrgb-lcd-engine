"""Low-rate renderer and HID transport for the reference 0x0416:0x5302 LCD.

This process is deliberately separate from SignalRGB's device plugin API. It
accepts small JSON settings datagrams from the SignalRGB network add-on and
owns the HID interface while running.
"""
from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass

try:
    import hid  # provided by the hidapi package
except ImportError:  # graceful startup allows installation/configuration first
    hid = None

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = ImageDraw = ImageFont = None

try:
    import psutil
except ImportError:
    psutil = None

VID, PID = 0x0416, 0x5302
USAGE_PAGE, USAGE = 0xFF06, 0x0001
WIDTH, HEIGHT = 240, 320
FRAME_BYTES = WIDTH * HEIGHT * 2
REPORT_BYTES = 512
MAGIC = bytes((0xDA, 0xDB, 0xDC, 0xDD))
UDP_HOST, UDP_PORT, REPLY_PORT = "127.0.0.1", 41720, 41721


@dataclass
class Settings:
    mode: str = "Dashboard"
    header_text: str = "SYSTEM MONITOR"
    accent: str = "#42D6C5"
    background: str = "#10151B"
    fps: int = 8
    brightness: int = 100
    clock_style: str = "24 Stunden"
    show_clock: bool = True
    show_cpu: bool = True
    show_ram: bool = True


def rgb565(image: Image.Image) -> bytes:
    """Convert RGB pixels to the little-endian RGB565 byte order in the JS reference."""
    out = bytearray(FRAME_BYTES)
    pixels = image.convert("RGB").resize((WIDTH, HEIGHT)).load()
    i = 0
    for y in range(HEIGHT):
        for x in range(WIDTH):
            r, g, b = pixels[x, y]
            value = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            out[i] = value & 0xFF
            out[i + 1] = value >> 8
            i += 2
    return bytes(out)


def render(settings: Settings, now: float, cpu_percent: float = 0.0, ram_percent: float = 0.0) -> bytes:
    if Image is None:
        raise RuntimeError("Pillow fehlt. Installiere service/requirements.txt.")
    image = Image.new("RGB", (WIDTH, HEIGHT), settings.background)
    draw = ImageDraw.Draw(image)
    accent = settings.accent
    font = ImageFont.load_default()
    draw.rounded_rectangle((12, 12, WIDTH - 12, HEIGHT - 12), radius=12, outline=accent, width=2)
    if settings.mode == "Clock":
        clock_fmt = "%I:%M:%S %p" if settings.clock_style == "12 Stunden" else "%H:%M:%S"
        draw.text((30, 105), time.strftime(clock_fmt), fill=accent, font=font, spacing=5)
        draw.text((30, 145), time.strftime("%d.%m.%Y"), fill="white", font=font)
    elif settings.mode == "Bars":
        draw.text((24, 28), "SYSTEM LOAD", fill="white", font=font)
        for n, (label, value) in enumerate((("CPU", cpu_percent), ("RAM", ram_percent))):
            y = 92 + n * 78
            draw.text((24, y), f"{label}  {value:.0f}%", fill="white", font=font)
            draw.rounded_rectangle((24, y + 23, 210, y + 39), radius=5, fill="#263541")
            draw.rounded_rectangle((24, y + 23, 24 + int(186 * max(0.0, min(100.0, value)) / 100), y + 39), radius=5, fill=accent)
    elif settings.mode == "Test Pattern":
        for n, color in enumerate(("#ff3344", "#33dd66", "#3388ff", "#ffffff", "#000000")):
            draw.rectangle((20, 35 + n * 48, WIDTH - 20, 70 + n * 48), fill=color)
    else:
        draw.text((24, 28), settings.header_text, fill=accent, font=font)
        y = 74
        if settings.show_clock:
            clock_fmt = "%I:%M:%S %p" if settings.clock_style == "12 Stunden" else "%H:%M:%S"
            draw.text((24, y), time.strftime(clock_fmt), fill="white", font=font)
            y += 42
        for label, value, enabled in (("CPU", cpu_percent, settings.show_cpu), ("RAM", ram_percent, settings.show_ram)):
            if not enabled:
                continue
            draw.text((24, y), f"{label}  {value:.0f}%", fill="white", font=font)
            y += 22
            draw.rounded_rectangle((24, y, 210, y + 13), radius=5, fill="#263541")
            draw.rounded_rectangle((24, y, 24 + int(186 * max(0.0, min(100.0, value)) / 100), y + 13), radius=5, fill=accent)
            y += 38
    if settings.brightness < 100:
        image = image.point(lambda channel: channel * settings.brightness // 100)
    return rgb565(image)


class HidDisplay:
    def __init__(self):
        self.device = None
        self.next_scan = 0.0

    def open(self) -> bool:
        if hid is None:
            print("hidapi is missing; run: python -m pip install -r service/requirements.txt")
            return False
        candidates = hid.enumerate(VID, PID)
        if not candidates:
            print(f"No HID device with VID:PID {VID:04X}:{PID:04X} was enumerated.")
            return False
        for info in candidates:
            if info.get("usage_page") != USAGE_PAGE or info.get("usage") != USAGE:
                print("Ignoring HID interface with unexpected usage:", info.get("usage_page"), info.get("usage"), info.get("interface_number"))
                continue
            try:
                print(f"Opening LCD HID interface {VID:04X}:{PID:04X}, usage page {USAGE_PAGE:04X}, usage {USAGE:04X}...")
                candidate = hid.device()
                candidate.open_path(info["path"])
                if self._handshake(candidate):
                    self.device = candidate
                    print("Reference LCD connected and handshake accepted.")
                    return True
                print("HID interface opened, but the LCD did not accept the expected handshake.")
                candidate.close()
            except Exception as exc:
                print(f"Could not open/use candidate HID endpoint: {type(exc).__name__}: {exc}")
        return False

    @staticmethod
    def _handshake(device) -> bool:
        report = bytearray(REPORT_BYTES + 1)
        report[1:5] = MAGIC
        report[13] = 1
        for _ in range(3):
            device.write(report)
            response = device.read(36, 500)
            # hidapi commonly strips report ID 0 on Windows, while SignalRGB's
            # device.read() returns it at index 0. Accept and normalize either.
            offset = 1 if len(response) >= 18 and bytes(response[1:5]) == MAGIC else 0
            if (len(response) >= offset + 17
                    and bytes(response[offset:offset + 4]) == MAGIC
                    and response[offset + 12] == 1
                    and response[offset + 16] == 0x10):
                print("LCD handshake accepted.")
                return True
            if response:
                print("Unexpected LCD handshake reply:", bytes(response[:min(len(response), 24)]).hex(" "))
            else:
                print("LCD handshake timed out (no HID reply).")
            time.sleep(0.25)
        return False

    def send_frame(self, pixels: bytes) -> None:
        if self.device is None:
            return
        header = bytearray(20)
        header[:4] = MAGIC
        header[4:8] = bytes((2, 0, 1, 0))
        header[8:10] = WIDTH.to_bytes(2, "little")
        header[10:12] = HEIGHT.to_bytes(2, "little")
        header[12:16] = bytes((2, 0, 0, 0))
        header[16:20] = FRAME_BYTES.to_bytes(4, "little")
        data = bytes(header) + pixels
        data += bytes((-len(data)) % REPORT_BYTES)
        for offset in range(0, len(data), REPORT_BYTES):
            self.device.write(bytes((0,)) + data[offset:offset + REPORT_BYTES])

    def close(self):
        if self.device is not None:
            try:
                self.device.close()
            finally:
                self.device = None


def main():
    settings = Settings()
    display = HidDisplay()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_HOST, UDP_PORT))
    sock.settimeout(0.2)
    previous = None
    last_frame = 0.0
    last_discovery = 0.0
    cpu_percent = 0.0
    ram_percent = 0.0
    last_metrics = 0.0
    print(f"LCD Engine helper listening on {UDP_HOST}:{UDP_PORT}")
    try:
        while True:
            now = time.monotonic()
            try:
                raw, _addr = sock.recvfrom(8192)
                message = json.loads(raw.decode("utf-8"))
                command = message.get("command")
                if command == "configure":
                    settings.mode = str(message.get("mode", settings.mode))
                    if settings.mode not in ("Dashboard", "Clock", "Bars", "Test Pattern"):
                        settings.mode = "Dashboard"
                    title = message.get("headerText", settings.header_text)
                    if isinstance(title, str):
                        settings.header_text = " ".join(title.split())[:22] or "SYSTEM MONITOR"
                    for key in ("accent", "background"):
                        value = message.get(key)
                        if isinstance(value, str) and len(value) == 7 and value.startswith("#"):
                            setattr(settings, key, value)
                    settings.fps = max(1, min(15, int(message.get("fps", settings.fps))))
                    settings.brightness = max(10, min(100, int(message.get("brightness", settings.brightness))))
                    settings.clock_style = "12 Stunden" if message.get("clockStyle") == "12 Stunden" else "24 Stunden"
                    settings.show_clock = message.get("showClock", True) not in (False, "false", "0", 0)
                    settings.show_cpu = message.get("showCpu", True) not in (False, "false", "0", 0)
                    settings.show_ram = message.get("showRam", True) not in (False, "false", "0", 0)
                elif command == "disconnect":
                    display.close()
                elif command == "discover":
                    pass
            except socket.timeout:
                pass
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                print(f"Ignoring malformed settings datagram: {exc}")

            if now - last_discovery >= 1:
                if display.device is None and now >= display.next_scan:
                    display.open()
                    display.next_scan = now + 5.0
                reply = {"service": "independent-lcd-engine-local", "command": "device",
                         "connected": display.device is not None,
                         "name": "Independent LCD Engine", "model": "0416:5302 reference HID"}
                try:
                    sock.sendto(json.dumps(reply).encode("utf-8"), (UDP_HOST, REPLY_PORT))
                except OSError:
                    pass
                last_discovery = now

            interval = 1.0 / max(1, settings.fps)
            if display.device is not None and now - last_frame >= interval:
                try:
                    if psutil is not None and now - last_metrics >= 1.0:
                        cpu_percent = psutil.cpu_percent(interval=None)
                        ram_percent = psutil.virtual_memory().percent
                        last_metrics = now
                    frame = render(settings, now, cpu_percent, ram_percent)
                    if frame != previous:
                        display.send_frame(frame)
                        previous = frame
                    last_frame = now
                except Exception as exc:
                    print(f"Frame render/transfer failed; reconnecting: {exc}")
                    display.close()
                    previous = None
    except KeyboardInterrupt:
        print("Stopping LCD Engine helper.")
    finally:
        display.close()
        sock.close()


if __name__ == "__main__":
    main()

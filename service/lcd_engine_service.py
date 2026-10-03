"""Low-rate renderer and HID transport for the reference 0x0416:0x5302 LCD.

This process is deliberately separate from SignalRGB's device plugin API. It
accepts small JSON settings datagrams from the SignalRGB network add-on and
owns the HID interface while running.
"""
from __future__ import annotations

import json
import base64
import io
import os
import socket
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import hid  # provided by the hidapi package
except ImportError:  # graceful startup allows installation/configuration first
    hid = None

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except ImportError:
    Image = ImageDraw = ImageFont = ImageOps = None

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
EDITOR_PORT = 41722


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
    capture_signalrgb: bool = False
    auto_scale: bool = True
    font_scale: int = 100
    background_dim: int = 0
    gradient_angle: int = 160
    image_fit: str = "Cover"
    safe_margin: int = 12
    rotation: int = 0
    background_mode: str = "Solid"
    background2: str = "#18313A"
    background_image: str = ""
    widgets: list = field(default_factory=lambda: [
        {"id": "title-1", "type": "title", "x": 18, "y": 24, "visible": True, "scale": 1.0, "color": "#FFFFFF", "text": "SYSTEM MONITOR"},
        {"id": "clock-1", "type": "clock", "x": 18, "y": 82, "visible": True, "scale": 1.0, "color": "#FFFFFF", "text": ""},
        {"id": "cpu-1", "type": "cpu", "x": 18, "y": 142, "visible": True, "scale": 1.0, "color": "#FFFFFF", "text": ""},
        {"id": "ram-1", "type": "ram", "x": 18, "y": 210, "visible": True, "scale": 1.0, "color": "#FFFFFF", "text": ""},
    ])
    effect_width: int = 0
    effect_height: int = 0
    effect_colors: list = field(default_factory=list)
    effect_received_at: float = 0.0
    gpu_percent: float | None = None
    gpu_temperature: float | None = None
    gpu_memory_used: float | None = None
    gpu_memory_total: float | None = None


CONFIG_PATH = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "IndependentLCDEngine" / "config.json"


def load_editor_config(settings: Settings) -> None:
    try:
        values = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        apply_editor_config(settings, values)
    except (OSError, ValueError, TypeError):
        pass


def apply_editor_config(settings: Settings, values: dict) -> None:
    if values.get("rotation") in (0, 90, 180, 270):
        settings.rotation = int(values["rotation"])
    if values.get("backgroundMode") in ("Solid", "Gradient", "Image", "SignalRGB Effect"):
        settings.background_mode = values["backgroundMode"]
    image_data = values.get("backgroundImage")
    if isinstance(image_data, str) and image_data.startswith("data:image/") and len(image_data) <= 1_000_000:
        settings.background_image = image_data
    if values.get("mode") in ("Dashboard", "Clock", "Bars", "Test Pattern", "Custom Layout"):
        settings.mode = values["mode"]
    title = values.get("headerText")
    if isinstance(title, str):
        settings.header_text = " ".join(title.split())[:22] or "SYSTEM MONITOR"
    if values.get("clockStyle") in ("24 Stunden", "12 Stunden"):
        settings.clock_style = values["clockStyle"]
    for key, attr in (("showClock", "show_clock"), ("showCPU", "show_cpu"), ("showRAM", "show_ram")):
        if key in values:
            setattr(settings, attr, bool(values[key]))
    if "fps" in values:
        settings.fps = max(1, min(15, int(values["fps"])))
    if "brightness" in values:
        settings.brightness = max(10, min(100, int(values["brightness"])))
    if "captureSignalRGB" in values:
        settings.capture_signalrgb = bool(values["captureSignalRGB"])
    if "autoScale" in values:
        settings.auto_scale = bool(values["autoScale"])
    if "fontScale" in values:
        settings.font_scale = max(60, min(180, int(values["fontScale"])))
    if "safeMargin" in values:
        settings.safe_margin = max(0, min(40, int(values["safeMargin"])))
    if "backgroundDim" in values:
        settings.background_dim = max(0, min(80, int(values["backgroundDim"])))
    if values.get("gradientAngle") in (0, 90, 180, 270):
        settings.gradient_angle = int(values["gradientAngle"])
    if values.get("imageFit") in ("Cover", "Contain", "Stretch"):
        settings.image_fit = values["imageFit"]
    for key in ("accent", "background", "background2"):
        value = values.get(key)
        if isinstance(value, str) and len(value) == 7 and value.startswith("#"):
            setattr(settings, key, value)
    widgets = values.get("widgets")
    allowed = {"title", "clock", "date", "cpu", "ram", "cpu_bar", "ram_bar", "gpu", "gpu_temp", "gpu_mem", "gpu_bar", "hostname", "uptime", "text"}
    if isinstance(widgets, list):
        clean = []
        seen_ids = set()
        for index, item in enumerate(widgets[:12]):
            if not isinstance(item, dict) or item.get("type") not in allowed:
                continue
            layout_width, layout_height = (HEIGHT, WIDTH) if settings.rotation in (90, 270) else (WIDTH, HEIGHT)
            widget_id = str(item.get("id", f"{item['type']}-{index}"))[:48]
            if widget_id in seen_ids:
                continue
            seen_ids.add(widget_id)
            color = item.get("color", "#FFFFFF")
            if not isinstance(color, str) or len(color) != 7 or not color.startswith("#"):
                color = "#FFFFFF"
            clean.append({"id": widget_id, "type": item["type"], "x": max(settings.safe_margin, min(layout_width - settings.safe_margin - 45, int(item.get("x", 0)))),
                          "y": max(settings.safe_margin, min(layout_height - settings.safe_margin - 28, int(item.get("y", 0)))),
                          "visible": bool(item.get("visible", True)),
                          "scale": max(0.5, min(2.5, float(item.get("scale", 1.0)))),
                          "color": color, "text": str(item.get("text", "Custom text"))[:32]})
        settings.widgets = clean


class EditorHandler(BaseHTTPRequestHandler):
    engine_settings: Settings

    def do_GET(self):
        if self.path == "/config":
            data = {"rotation": self.engine_settings.rotation,
                    "mode": self.engine_settings.mode,
                    "headerText": self.engine_settings.header_text,
                    "clockStyle": self.engine_settings.clock_style,
                    "showClock": self.engine_settings.show_clock,
                    "showCPU": self.engine_settings.show_cpu,
                    "showRAM": self.engine_settings.show_ram,
                    "captureSignalRGB": self.engine_settings.capture_signalrgb,
                    "autoScale": self.engine_settings.auto_scale,
                    "fontScale": self.engine_settings.font_scale,
                    "safeMargin": self.engine_settings.safe_margin,
                    "backgroundDim": self.engine_settings.background_dim,
                    "gradientAngle": self.engine_settings.gradient_angle,
                    "imageFit": self.engine_settings.image_fit,
                    "fps": self.engine_settings.fps,
                    "brightness": self.engine_settings.brightness,
                    "backgroundMode": self.engine_settings.background_mode,
                    "accent": self.engine_settings.accent,
                    "background": self.engine_settings.background,
                    "background2": self.engine_settings.background2,
                    "backgroundImage": self.engine_settings.background_image,
                    "effectActive": self.engine_settings.effect_received_at > 0 and time.monotonic() - self.engine_settings.effect_received_at < 2.0,
                    "gpuAvailable": self.engine_settings.gpu_percent is not None,
                    "gpuPercent": self.engine_settings.gpu_percent,
                    "gpuTemperature": self.engine_settings.gpu_temperature,
                    "gpuMemoryUsed": self.engine_settings.gpu_memory_used,
                    "gpuMemoryTotal": self.engine_settings.gpu_memory_total,
                    "widgets": self.engine_settings.widgets}
            payload = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        elif self.path == "/" or self.path == "/editor.html":
            payload = (Path(__file__).with_name("editor.html")).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        else:
            self.send_error(404)
            return
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        if self.path != "/config":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length < 2 or length > 1_000_000:
            self.send_error(413)
            return
        try:
            values = json.loads(self.rfile.read(length))
            apply_editor_config(self.engine_settings, values)
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(json.dumps({"rotation": self.engine_settings.rotation,
                "mode": self.engine_settings.mode, "headerText": self.engine_settings.header_text,
                "clockStyle": self.engine_settings.clock_style, "showClock": self.engine_settings.show_clock,
                "showCPU": self.engine_settings.show_cpu, "showRAM": self.engine_settings.show_ram,
                "captureSignalRGB": self.engine_settings.capture_signalrgb,
                "autoScale": self.engine_settings.auto_scale, "fontScale": self.engine_settings.font_scale,
                "safeMargin": self.engine_settings.safe_margin,
                "backgroundDim": self.engine_settings.background_dim, "gradientAngle": self.engine_settings.gradient_angle,
                "imageFit": self.engine_settings.image_fit,
                "fps": self.engine_settings.fps, "brightness": self.engine_settings.brightness,
                "backgroundMode": self.engine_settings.background_mode,
                "accent": self.engine_settings.accent, "background": self.engine_settings.background,
                "background2": self.engine_settings.background2, "backgroundImage": self.engine_settings.background_image,
                "widgets": self.engine_settings.widgets},
                indent=2), encoding="utf-8")
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"OK")
        except (ValueError, TypeError, OSError):
            self.send_error(400)

    def log_message(self, _format, *_args):
        pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()


def start_editor(settings: Settings) -> None:
    load_editor_config(settings)
    handler = type("BoundEditorHandler", (EditorHandler,), {"engine_settings": settings})
    server = ThreadingHTTPServer(("127.0.0.1", EDITOR_PORT), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"LCD visual editor: http://127.0.0.1:{EDITOR_PORT}/")


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
    canvas_width, canvas_height = (HEIGHT, WIDTH) if settings.rotation in (90, 270) else (WIDTH, HEIGHT)
    if settings.background_mode == "SignalRGB Effect" and settings.effect_width * settings.effect_height * 3 == len(settings.effect_colors):
        effect = bytes(max(0, min(255, int(value))) for value in settings.effect_colors)
        image = Image.frombytes("RGB", (settings.effect_width, settings.effect_height), effect).resize((canvas_width, canvas_height), Image.Resampling.BILINEAR)
    elif settings.background_mode == "Image" and settings.background_image:
        try:
            encoded = settings.background_image.split(",", 1)[1]
            raw_image = base64.b64decode(encoded, validate=True)
            source = Image.open(io.BytesIO(raw_image)).convert("RGB")
            if settings.image_fit == "Contain":
                source.thumbnail((canvas_width, canvas_height), Image.Resampling.LANCZOS)
                image = Image.new("RGB", (canvas_width, canvas_height), settings.background)
                image.paste(source, ((canvas_width - source.width) // 2, (canvas_height - source.height) // 2))
            elif settings.image_fit == "Cover":
                image = ImageOps.fit(source, (canvas_width, canvas_height), method=Image.Resampling.LANCZOS)
            else:
                image = source.resize((canvas_width, canvas_height), Image.Resampling.LANCZOS)
        except (ValueError, OSError, IndexError):
            image = Image.new("RGB", (canvas_width, canvas_height), settings.background)
    elif settings.background_mode == "Gradient":
        top, bottom = Image.new("RGB", (1, 1), settings.background).getpixel((0, 0)), Image.new("RGB", (1, 1), settings.background2).getpixel((0, 0))
        image = Image.new("RGB", (canvas_width, canvas_height))
        draw_gradient = ImageDraw.Draw(image)
        horizontal = settings.gradient_angle in (90, 270)
        dimension = canvas_width if horizontal else canvas_height
        for pos in range(dimension):
            t = pos / max(1, dimension - 1)
            if settings.gradient_angle in (180, 270):
                t = 1.0 - t
            color = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
            if horizontal:
                draw_gradient.line((pos, 0, pos, canvas_height), fill=color)
            else:
                draw_gradient.line((0, pos, canvas_width, pos), fill=color)
    else:
        image = Image.new("RGB", (canvas_width, canvas_height), settings.background)
    if settings.background_dim:
        image = image.point(lambda channel: channel * (100 - settings.background_dim) // 100)
    draw = ImageDraw.Draw(image)
    accent = settings.accent
    orientation_scale = min(canvas_width / WIDTH, canvas_height / HEIGHT) if settings.auto_scale else 1.0
    try:
        font_path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeui.ttf"
        font = ImageFont.truetype(str(font_path), max(9, round(14 * settings.font_scale / 100 * orientation_scale)))
    except OSError:
        font = ImageFont.load_default()
    draw.rounded_rectangle((12, 12, canvas_width - 12, canvas_height - 12), radius=12, outline=accent, width=2)
    if settings.mode == "Clock":
        clock_fmt = "%I:%M:%S %p" if settings.clock_style == "12 Stunden" else "%H:%M:%S"
        if settings.show_clock:
            draw.text((30, 105), time.strftime(clock_fmt), fill=accent, font=font, spacing=5)
            draw.text((30, 145), time.strftime("%d.%m.%Y"), fill="white", font=font)
    elif settings.mode == "Bars":
        draw.text((24, 28), settings.header_text, fill=accent, font=font)
        bars = []
        if settings.show_cpu:
            bars.append(("CPU", cpu_percent))
        if settings.show_ram:
            bars.append(("RAM", ram_percent))
        if settings.gpu_percent is not None:
            bars.append(("GPU", settings.gpu_percent))
        for n, (label, value) in enumerate(bars):
            y = 92 + n * 78
            draw.text((24, y), f"{label}  {value:.0f}%", fill="white", font=font)
            bar_right = canvas_width - 24
            draw.rounded_rectangle((24, y + 23, bar_right, y + 39), radius=5, fill="#263541")
            draw.rounded_rectangle((24, y + 23, 24 + int((bar_right - 24) * max(0.0, min(100.0, value)) / 100), y + 39), radius=5, fill=accent)
    elif settings.mode == "Test Pattern":
        for n, color in enumerate(("#ff3344", "#33dd66", "#3388ff", "#ffffff", "#000000")):
            draw.rectangle((20, 25 + n * (canvas_height - 50) // 5, canvas_width - 20, 25 + (n + 1) * (canvas_height - 50) // 5), fill=color)
    else:
        uptime_seconds = int(time.time() - psutil.boot_time()) if psutil is not None else 0
        uptime_text = f"UPTIME  {uptime_seconds // 86400}d {(uptime_seconds % 86400) // 3600:02d}h"
        values = {"title": settings.header_text,
                  "clock": time.strftime("%I:%M:%S %p" if settings.clock_style == "12 Stunden" else "%H:%M:%S"),
                  "date": time.strftime("%d.%m.%Y"), "cpu": f"CPU  {cpu_percent:.0f}%",
                  "ram": f"RAM  {ram_percent:.0f}%", "hostname": socket.gethostname(),
                  "uptime": uptime_text, "text": ""}
        values["gpu"] = f"GPU  {settings.gpu_percent:.0f}%" if settings.gpu_percent is not None else "GPU  n/v"
        values["gpu_temp"] = f"GPU  {settings.gpu_temperature:.0f}°C" if settings.gpu_temperature is not None else "GPU  n/v"
        values["gpu_mem"] = (f"GPU RAM  {settings.gpu_memory_used:.0f}/{settings.gpu_memory_total:.0f} MB"
                             if settings.gpu_memory_used is not None and settings.gpu_memory_total is not None else "GPU RAM  n/v")
        for widget in settings.widgets:
            kind = widget["type"]
            if not widget.get("visible", True):
                continue
            if kind == "clock" and not settings.show_clock:
                continue
            if kind in ("cpu", "cpu_bar") and not settings.show_cpu:
                continue
            if kind in ("ram", "ram_bar") and not settings.show_ram:
                continue
            x, y = widget["x"], widget["y"]
            widget_font = font
            widget_size = max(9, round(14 * settings.font_scale / 100 * orientation_scale * float(widget.get("scale", 1.0))))
            try:
                widget_font = ImageFont.truetype(str(font_path), widget_size)
            except (OSError, NameError):
                pass
            if kind in ("title", "clock", "date", "hostname", "uptime", "text", "cpu", "ram", "gpu", "gpu_temp", "gpu_mem"):
                text = widget.get("text", "") if kind == "text" else values.get(kind, "")
                if kind == "title":
                    text = widget.get("text") or settings.header_text
                draw.text((x, y), text, fill=widget.get("color", accent if kind == "title" else "#FFFFFF"), font=widget_font)
            elif kind in ("cpu_bar", "ram_bar", "gpu_bar"):
                value = cpu_percent if kind == "cpu_bar" else ram_percent if kind == "ram_bar" else settings.gpu_percent or 0.0
                label = "CPU" if kind == "cpu_bar" else "RAM" if kind == "ram_bar" else "GPU"
                draw.text((x, y), f"{label}  {value:.0f}%", fill=widget.get("color", "#FFFFFF"), font=widget_font)
                widget_scale = float(widget.get("scale", 1.0))
                bar_y = min(canvas_height - 18, y + round(20 * widget_scale))
                bar_right = min(canvas_width - 12, x + round(186 * widget_scale))
                bar_height = max(6, round(12 * widget_scale))
                draw.rounded_rectangle((x, bar_y, bar_right, bar_y + bar_height), radius=5, fill="#263541")
                end_x = min(bar_right, x + int((bar_right - x) * max(0.0, min(100.0, value)) / 100))
                draw.rounded_rectangle((x, bar_y, end_x, bar_y + bar_height), radius=5, fill=widget.get("color", accent))
    if settings.rotation:
        image = image.rotate(-settings.rotation, expand=True)
    image = image.resize((WIDTH, HEIGHT), Image.Resampling.BILINEAR)
    if settings.brightness < 100:
        image = image.point(lambda channel: channel * settings.brightness // 100)
    return rgb565(image)


def read_nvidia_gpu() -> tuple[float | None, float | None, float | None, float | None]:
    """Read aggregate NVIDIA GPU metrics through the vendor CLI when available."""
    executable = shutil.which("nvidia-smi")
    if not executable:
        # Windows exposes a vendor-neutral 3D utilization counter for modern
        # WDDM drivers. Temperature and VRAM remain vendor-specific metrics.
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            return None, None, None, None
        command = "$g=Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine -ErrorAction SilentlyContinue | Where-Object {$_.Name -match 'engtype_3D'}; if($g){($g | Measure-Object UtilizationPercentage -Maximum).Maximum}"
        try:
            result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", command],
                                    capture_output=True, text=True, timeout=1.5, check=True,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            value = float(result.stdout.strip().replace(",", "."))
            return max(0.0, min(100.0, value)), None, None, None
        except (OSError, subprocess.SubprocessError, ValueError):
            return None, None, None, None
    try:
        result = subprocess.run(
            [executable, "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=1.2, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        rows = []
        for line in result.stdout.splitlines():
            columns = [part.strip() for part in line.split(",")]
            if len(columns) >= 4 and all(value.replace(".", "", 1).isdigit() for value in columns[:4]):
                rows.append(tuple(float(value) for value in columns[:4]))
        if not rows:
            return None, None, None, None
        count = len(rows)
        return (sum(row[0] for row in rows) / count,
                max(row[1] for row in rows),
                sum(row[2] for row in rows), sum(row[3] for row in rows))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None, None, None, None


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
    start_editor(settings)
    previous = None
    last_frame = 0.0
    last_discovery = 0.0
    cpu_percent = 0.0
    ram_percent = 0.0
    last_metrics = 0.0
    last_gpu_metrics = 0.0
    print(f"LCD Engine helper listening on {UDP_HOST}:{UDP_PORT}")
    try:
        while True:
            now = time.monotonic()
            try:
                raw, _addr = sock.recvfrom(8192)
                message = json.loads(raw.decode("utf-8"))
                command = message.get("command")
                if command == "effect-frame":
                    width = int(message.get("width", 0))
                    height = int(message.get("height", 0))
                    colors = message.get("colors", [])
                    if 1 <= width <= 32 and 1 <= height <= 32 and isinstance(colors, list) and len(colors) == width * height * 3:
                        settings.effect_width, settings.effect_height = width, height
                        settings.effect_colors = colors
                        settings.effect_received_at = time.monotonic()
                elif command == "configure":
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
                         "captureSignalRGB": settings.capture_signalrgb,
                         "name": "Independent LCD Engine", "model": "0416:5302 reference HID"}
                try:
                    sock.sendto(json.dumps(reply).encode("utf-8"), (UDP_HOST, REPLY_PORT))
                except OSError:
                    pass
                last_discovery = now

            if now - last_gpu_metrics >= 2.0:
                (settings.gpu_percent, settings.gpu_temperature,
                 settings.gpu_memory_used, settings.gpu_memory_total) = read_nvidia_gpu()
                last_gpu_metrics = now

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

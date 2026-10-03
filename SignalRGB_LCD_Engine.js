import udp from "@SignalRGB/udp";

/* global controller, discovery, service, device, ViewMode, AccentColor, BackgroundColor, TargetFPS, Brightness, ShowClock, ShowCPU, ShowRAM, ClockStyle, HeaderText */

const SERVICE_NAME = "Independent LCD Engine";
const SERVICE_ID = "independent-lcd-engine-local";
const HELPER_IP = "127.0.0.1";
const HELPER_PORT = 41720;
const DISCOVERY_RATE_MS = 5000;
const SETTINGS_RATE_MS = 1000;

let lastSettingsSend = 0;
let lastDiscoverySend = 0;
let registered = false;

export function Name() { return SERVICE_NAME; }
export function Version() { return "0.1.0"; }
export function Publisher() { return "Independent LCD Engine"; }
export function Type() { return "network"; }
export function Size() { return [1, 1]; }
export function SubdeviceController() { return true; }
export function DefaultPosition() { return [0, 0]; }
export function DefaultScale() { return 1.0; }
export function DeviceMessage() {
    return ["Independent LCD Engine service", "Start the local LCD Engine helper to discover the display."];
}

export function ControllableParameters() {
    return [
        { property: "ViewMode", group: "lcd", label: "Ansicht", type: "combobox", values: ["Dashboard", "Clock", "Bars", "Test Pattern"], default: "Dashboard" },
        { property: "HeaderText", group: "lcd", label: "Überschrift", type: "textfield", default: "SYSTEM MONITOR" },
        { property: "ClockStyle", group: "lcd", label: "Uhrformat", type: "combobox", values: ["24 Stunden", "12 Stunden"], default: "24 Stunden" },
        { property: "ShowClock", group: "widgets", label: "Uhr anzeigen", type: "boolean", default: true },
        { property: "ShowCPU", group: "widgets", label: "CPU anzeigen", type: "boolean", default: true },
        { property: "ShowRAM", group: "widgets", label: "Arbeitsspeicher anzeigen", type: "boolean", default: true },
        { property: "AccentColor", group: "lcd", label: "Akzentfarbe", type: "color", default: "#42D6C5" },
        { property: "BackgroundColor", group: "lcd", label: "Hintergrund", type: "color", default: "#10151B" },
        { property: "TargetFPS", group: "lcd", label: "Bildrate", type: "number", min: "1", max: "15", default: "8" },
        { property: "Brightness", group: "lcd", label: "Helligkeit", type: "number", min: "10", max: "100", default: "100" }
    ];
}

export function Initialize() {
    if (typeof controller !== "undefined" && controller && controller.name) {
        device.setName(controller.name);
    }
    device.addFeature("udp");
    lastSettingsSend = 0;
}

export function Render() {
    const now = Date.now();
    if (now - lastSettingsSend < SETTINGS_RATE_MS) return;
    lastSettingsSend = now;
    udp.send(HELPER_IP, HELPER_PORT, JSON.stringify({
        service: SERVICE_ID,
        command: "configure",
        mode: String(ViewMode || "Dashboard"),
        headerText: String(HeaderText || "SYSTEM MONITOR").slice(0, 22),
        clockStyle: String(ClockStyle || "24 Stunden"),
        showClock: ShowClock !== false && ShowClock !== "0",
        showCpu: ShowCPU !== false && ShowCPU !== "0",
        showRam: ShowRAM !== false && ShowRAM !== "0",
        accent: normalizeColor(AccentColor, "#42D6C5"),
        background: normalizeColor(BackgroundColor, "#10151B"),
        fps: clamp(Number(TargetFPS), 1, 15, 8),
        brightness: clamp(Number(Brightness), 10, 100, 100)
    }));
}

export function Shutdown() {
    udp.send(HELPER_IP, HELPER_PORT, JSON.stringify({ service: SERVICE_ID, command: "disconnect" }));
}

export function DiscoveryService() {
    this.IconUrl = "https://assets.signalrgb.com/brands/products/govee_ble/icon@2x.png";
    this.UdpBroadcastPort = HELPER_PORT;
    this.UdpListenPort = 41721;
    this.UdpBroadcastAddress = HELPER_IP;
    this.controllers = new Map();

    this.Initialize = function() {
        service.log(`${SERVICE_NAME}: starting local helper discovery`);
    };

    this.Update = function() {
        const now = Date.now();
        if (now - lastDiscoverySend < DISCOVERY_RATE_MS) return;
        lastDiscoverySend = now;
        service.broadcast(JSON.stringify({ service: SERVICE_ID, command: "discover" }));
    };

    this.Discovered = function(value) {
        let response;
        try { response = JSON.parse(value.response); }
        catch (_) { return; }
        if (!response || response.service !== SERVICE_ID || response.command !== "device") return;
        if (!response.connected) {
            service.log(`${SERVICE_NAME}: helper found, LCD not connected`);
            return;
        }

        let existing = service.getController(SERVICE_ID);
        if (!existing) {
            existing = new LCDServiceController(response);
            service.addController(existing);
        } else {
            existing.updateWithValue(response);
        }
        existing.update();
    };

    this.remove = function(controllerObj) {
        if (controllerObj) service.removeController(controllerObj);
        else {
            const existing = service.getController(SERVICE_ID);
            if (existing) service.removeController(existing);
        }
    };
}

class LCDServiceController {
    constructor(info) {
        this.id = SERVICE_ID;
        this.name = info.name || "Independent LCD Engine";
        this.sku = info.model || "LCD service";
        this.productUUID = "INDEPENDENT_LCD_ENGINE";
        this.ip = HELPER_IP;
        this.port = HELPER_PORT;
        this.deviceImage = "";
        this.initialized = false;
        this.connected = Boolean(info.connected);
    }

    updateWithValue(info) {
        this.name = info.name || this.name;
        this.sku = info.model || this.sku;
        this.connected = Boolean(info.connected);
        service.updateController(this);
    }

    update() {
        if (this.initialized) return;
        this.initialized = true;
        service.updateController(this);
        service.announceController(this);
    }
}

function normalizeColor(value, fallback) {
    const s = String(value || fallback);
    return /^#[0-9a-f]{6}$/i.test(s) ? s : fallback;
}
function clamp(value, min, max, fallback) {
    return Number.isFinite(value) ? Math.max(min, Math.min(max, value)) : fallback;
}

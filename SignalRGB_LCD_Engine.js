import udp from "@SignalRGB/udp";

/* global controller, discovery, service, device */

const SERVICE_NAME = "Independent LCD Engine";
const SERVICE_ID = "independent-lcd-engine-local";
const HELPER_IP = "127.0.0.1";
const HELPER_PORT = 41720;
const DISCOVERY_RATE_MS = 5000;
const EFFECT_RATE_MS = 125;
const EFFECT_WIDTH = 16;
const EFFECT_HEIGHT = 20;

let lastDiscoverySend = 0;
let lastEffectSend = 0;
let effectSamplingErrorLogged = false;
let effectCaptureEnabled = false;

export function Name() { return SERVICE_NAME; }
export function Version() { return "0.1.0"; }
export function Publisher() { return "Independent LCD Engine"; }
export function Type() { return "network"; }
export function Size() { return [EFFECT_WIDTH, EFFECT_HEIGHT]; }
export function SubdeviceController() { return true; }
export function DefaultPosition() { return [0, 0]; }
export function DefaultScale() { return 1.0; }
export function DeviceMessage() {
    return ["Independent LCD Engine service", "Start the local LCD Engine helper to discover the display."];
}

export function Initialize() {
    if (typeof controller !== "undefined" && controller && controller.name) {
        device.setName(controller.name);
    }
    device.addFeature("udp");
}

export function Render() {
    const now = Date.now();
    if (effectCaptureEnabled && now - lastEffectSend >= EFFECT_RATE_MS) {
        lastEffectSend = now;
        const colors = [];
        try {
            for (let y = 0; y < EFFECT_HEIGHT; y++) {
                for (let x = 0; x < EFFECT_WIDTH; x++) {
                    const color = device.color(x, y);
                    colors.push(color[0], color[1], color[2]);
                }
            }
            udp.send(HELPER_IP, HELPER_PORT, JSON.stringify({
                service: SERVICE_ID, command: "effect-frame",
                width: EFFECT_WIDTH, height: EFFECT_HEIGHT, colors: colors
            }));
        } catch (error) {
            if (!effectSamplingErrorLogged) {
                service.log(`${SERVICE_NAME}: current effect sampling unavailable: ${error}`);
                effectSamplingErrorLogged = true;
            }
        }
    }
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
        effectCaptureEnabled = Boolean(response.captureSignalRGB);
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


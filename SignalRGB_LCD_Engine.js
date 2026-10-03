/* global service */

const SERVICE_NAME = "Independent LCD Engine";
const SERVICE_ID = "independent-lcd-engine-local";
const HELPER_IP = "127.0.0.1";
const HELPER_PORT = 41720;
const DISCOVERY_RATE_MS = 5000;

let lastDiscoverySend = 0;

export function Name() { return SERVICE_NAME; }
export function Version() { return "0.2.0"; }
export function Publisher() { return "Independent LCD Engine"; }
export function Type() { return "network"; }
export function Size() { return [16, 20]; }
export function SubdeviceController() { return true; }
export function DefaultPosition() { return [0, 0]; }
export function DefaultScale() { return 1.0; }
export function DeviceMessage() {
    return ["Independent LCD Engine service", "Start the local LCD Engine helper to discover the display."];
}

export function Initialize() {
    service.log(`${SERVICE_NAME}: waiting for the Thermalright device-plugin bridge`);
}

export function Render() {}

export function Shutdown() {}

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


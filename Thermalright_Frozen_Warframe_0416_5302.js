// @ts-nocheck
import LCD from "@SignalRGB/lcd";
import { udp } from "@SignalRGB/udp";

const REPORT_SIZE = 512;
const WIDTH = 320;
const HEIGHT = 240;
const FRAME_SIZE = WIDTH * HEIGHT * 2;
let initialized = false;

// 1. Framerate-Begrenzung: 15 FPS = ~66ms Abstand (spart enorm Leistung)
const TARGET_FPS = 15;
const FRAME_INTERVAL = 1000 / TARGET_FPS;
let lastFrameTime = 0;

// 2. Speicher für Delta-Check (Prüft ob sich das Bild geändert hat)
let previousFrame = null;
const HELPER_IP = "127.0.0.1";
const HELPER_PORT = 41720;
const PLUGIN_PORT = 41723;
const EFFECT_WIDTH = 16;
const EFFECT_HEIGHT = 20;
const EFFECT_INTERVAL = 125;
const OUTPUT_CHUNK_BYTES = 1200;
const OUTPUT_HEADER_BYTES = 12;
let bridgeSocket = null;
let lastEffectSend = 0;
let lastHeartbeat = 0;
let pendingOutputFrame = null;
let outputAssembly = null;
let outputFrameId = 0;
let udpErrorLogged = false;

// Vorberechnete, permanente Standard-Arrays
const rotatedPixels = new Array(FRAME_SIZE).fill(0);

const header = [
    0xDA, 0xDB, 0xDC, 0xDD,
    0x02, 0x00, 0x01, 0x00,
    240, 0x00,
    320 & 0xFF, (320 >> 8) & 0xFF,
    0x02, 0x00, 0x00, 0x00,
    FRAME_SIZE & 0xFF, (FRAME_SIZE >>> 8) & 0xFF, (FRAME_SIZE >>> 16) & 0xFF, (FRAME_SIZE >>> 24) & 0xFF
];

const packetBuffer = new Array(header.length + FRAME_SIZE).fill(0);
for (let i = 0; i < header.length; i++) {
    packetBuffer[i] = header[i];
}

export function Name() { return "Thermalright Frozen Warframe"; }
export function VendorId() { return 0x0416; }
export function ProductId() { return 0x5302; }
export function Publisher() { return "WhirlwindFx"; }
export function Type() { return "hid"; }
export function DeviceType() { return "lcd"; }
export function SubdeviceController() { return true; }
export function Size() { return [1, 1]; }
export function ConflictingProcesses() { return ["TRCC.exe", "USBLCDNEW.exe"]; }

export function Validate(endpoint) {
    return endpoint.interface === 0 && endpoint.usage_page === 0xFF06 && endpoint.usage === 0x0001;
}

export function Initialize() {
    initialized = handshake();
    if (!initialized) {
        device.notify("Thermalright LCD handshake failed", "Close TRCC, unplug/reconnect the AIO USB cable, then reload this plugin.", 1);
        return;
    }
    LCD.initialize({ width: WIDTH, height: HEIGHT, circular: false });
    bridgeSocket = udp.createSocket();
    bridgeSocket.on("message", receiveOutputChunk);
    bridgeSocket.on("error", error => {
        if (!udpErrorLogged) {
            device.log(`LCD Engine UDP bridge error: ${error}`);
            udpErrorLogged = true;
        }
    });
    bridgeSocket.bind(PLUGIN_PORT);
    device.setName("Thermalright Frozen Warframe (320x240)");
}

export function Render() {
    if (!initialized) return;

    // Keep the bridge alive and sample the upstream frame at a bounded rate.
    const now = Date.now();
    if (now - lastHeartbeat >= 1000) {
        lastHeartbeat = now;
        bridgeSocket.write(JSON.stringify({service: "independent-lcd-engine-local", command: "bridge-ready"}), HELPER_IP, HELPER_PORT);
    }
    if (now - lastEffectSend >= EFFECT_INTERVAL) {
        lastEffectSend = now;
        const naturalFrame = LCD.getFrame({ format: "RGB565" });
        if (naturalFrame && naturalFrame.length === FRAME_SIZE) {
            bridgeSocket.write(JSON.stringify({
                service: "independent-lcd-engine-local", command: "effect-frame",
                width: EFFECT_WIDTH, height: EFFECT_HEIGHT,
                colors: sampleRgb565(naturalFrame, EFFECT_WIDTH, EFFECT_HEIGHT)
            }), HELPER_IP, HELPER_PORT);
        }
    }

    // The helper owns layout/rendering; this device plugin remains the sole HID writer.
    if (!pendingOutputFrame || now - lastFrameTime < FRAME_INTERVAL) return;
    lastFrameTime = now;
    for (let i = 0; i < FRAME_SIZE; i++) {
        packetBuffer[header.length + i] = pendingOutputFrame[i];
    }
    writeFrame(packetBuffer);
    pendingOutputFrame = null;
}

export function Shutdown() {
    if (bridgeSocket) bridgeSocket.close();
    bridgeSocket = null;
    initialized = false;
}

function sampleRgb565(frame, sampleWidth, sampleHeight) {
    const colors = [];
    for (let y = 0; y < sampleHeight; y++) {
        const sourceY = Math.min(HEIGHT - 1, Math.floor((y + 0.5) * HEIGHT / sampleHeight));
        for (let x = 0; x < sampleWidth; x++) {
            const sourceX = Math.min(WIDTH - 1, Math.floor((x + 0.5) * WIDTH / sampleWidth));
            const offset = (sourceY * WIDTH + sourceX) * 2;
            const value = (frame[offset] & 0xff) | ((frame[offset + 1] & 0xff) << 8);
            colors.push(Math.round(((value >> 11) & 0x1f) * 255 / 31),
                        Math.round(((value >> 5) & 0x3f) * 255 / 63),
                        Math.round((value & 0x1f) * 255 / 31));
        }
    }
    return colors;
}

function receiveOutputChunk(data) {
    const bytes = Array.from(data);
    if (bytes.length <= OUTPUT_HEADER_BYTES || bytes[0] !== 0x49 || bytes[1] !== 0x4c || bytes[2] !== 0x43 || bytes[3] !== 0x44) return;
    const frameId = (bytes[4] | (bytes[5] << 8) | (bytes[6] << 16) | (bytes[7] << 24)) >>> 0;
    const part = bytes[8] | (bytes[9] << 8);
    const count = bytes[10] | (bytes[11] << 8);
    if (!count || part >= count || count > 256) return;
    if (!outputAssembly || outputAssembly.id !== frameId) {
        outputAssembly = {id: frameId, count: count, received: 0, parts: {}, frame: new Array(FRAME_SIZE).fill(0)};
    }
    if (outputAssembly.count !== count || outputAssembly.parts[part]) return;
    const start = part * OUTPUT_CHUNK_BYTES;
    const payload = bytes.slice(OUTPUT_HEADER_BYTES);
    for (let i = 0; i < payload.length && start + i < FRAME_SIZE; i++) outputAssembly.frame[start + i] = payload[i];
    outputAssembly.parts[part] = true;
    outputAssembly.received++;
    if (outputAssembly.received === count) {
        pendingOutputFrame = outputAssembly.frame;
        outputFrameId = frameId;
        outputAssembly = null;
    }
}

function writeFrame(source) {
    let sendBuffer = source;
    const remainder = source.length % REPORT_SIZE;
    if (remainder) sendBuffer = source.concat(new Array(REPORT_SIZE - remainder).fill(0));
    for (let offset = 0; offset < sendBuffer.length; offset += REPORT_SIZE) {
        device.write([0x00].concat(sendBuffer.slice(offset, offset + REPORT_SIZE)), REPORT_SIZE + 1);
    }
}

// Schneller Delta-Check mit Stichproben (prüft jedes 64. Byte für minimale Latenz)
function hasFrameChanged(newFrame, oldFrame) {
    if (!oldFrame) return true;
    for (let i = 0; i < FRAME_SIZE; i += 64) {
        if (newFrame[i] !== oldFrame[i]) return true;
    }
    return false;
}

function handshake() {
    const report = new Array(REPORT_SIZE + 1).fill(0);
    report[1] = 0xDA; report[2] = 0xDB; report[3] = 0xDC; report[4] = 0xDD;
    report[13] = 0x01;

    for (let attempt = 0; attempt < 3; attempt++) {
        device.write(report, report.length);
        const response = device.read([], 36, 500);
        const length = device.getLastReadSize();
        if (response && length >= 18 && response[1] === 0xDA && response[2] === 0xDB && response[3] === 0xDC && response[4] === 0xDD && response[13] === 0x01 && response[17] === 0x10) {
            console.log(`Frozen Warframe handshake OK: PM=0x${response[6].toString(16)}, SUB=0x${response[5].toString(16)}`);
            return true;
        }
        device.pause(250);
    }
    return false;
}

function rotate90CW(source, destination, sourceWidth, sourceHeight) {
    const destinationWidth = sourceHeight;
    const destinationHeight = sourceWidth;

    for (let y = 0; y < destinationHeight; y++) {
        const dstRowOffset = y * destinationWidth * 2;
        for (let x = 0; x < destinationWidth; x++) {
            const sourceIndex = ((sourceHeight - 1 - x) * sourceWidth + y) * 2;
            const destinationIndex = dstRowOffset + (x * 2);

            destination[destinationIndex]     = source[sourceIndex];
            destination[destinationIndex + 1] = source[sourceIndex + 1];
        }
    }
}

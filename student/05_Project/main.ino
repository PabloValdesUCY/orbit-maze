#include <Lab3Support.h>

#include "Features.h"
#include "Model.h"
#include "WirelessStream.h"

static MotionWindow window;
static uint32_t lastPoll = 0;
static uint32_t lastDisplayUpdate = 0;
static bool boardReady = false;
static bool displayReady = false;
static bool imuReady = false;
static bool serialConnected = false;
static bool serialGapPending = false;
static bool hasResult = false;
static int lastPrediction = -1;
static char statusLine[96];

static void resetWindow() {
    window.reset();
    hasResult = false;
    lastPrediction = -1;
}

static void resetForLinkChange() {
    resetWindow();
    WirelessStream::publish("# DATA_GAP\n");
}

static void serviceSerial() {
    const bool connected = static_cast<bool>(Serial);
    if (connected != serialConnected) {
        resetForLinkChange();
        serialConnected = connected;
        serialGapPending = false;
        if (connected) {
            Serial.print("\n# USB_CONNECTED\n");
            Serial.print(statusLine);
        }
    }
    if (serialGapPending) {
        constexpr char message[] = "\n# SERIAL_GAP\n";
        serialGapPending = Serial.write(reinterpret_cast<const uint8_t*>(message),
                                        sizeof(message) - 1) != sizeof(message) - 1;
        if (!serialGapPending) resetForLinkChange();
    }
    while (Serial.available() > 0) {
        const int command = Serial.read();
        if (command == 'r') {
            resetForLinkChange();
            Serial.println("# WINDOW_RESET");
        } else if (command == '?') {
            Serial.print(statusLine);
        }
    }
}

static bool writeSample(uint32_t timestamp, const float values[MOTION_CHANNEL_COUNT]) {
    if (!serialConnected && !WirelessStream::connected()) return true;
    char line[128];
    // Nine significant digits preserve each float32 value when the CSV is read back.
    const int length = snprintf(line, sizeof(line), "DATA,%lu,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g\n",
                                static_cast<unsigned long>(timestamp),
                                values[0], values[1], values[2], values[3], values[4], values[5]);
    if (length <= 0 || static_cast<size_t>(length) >= sizeof(line)) return false;
    WirelessStream::publish(line, length);
    if (!serialConnected || serialGapPending) return true;
    return Serial.write(reinterpret_cast<const uint8_t*>(line),
                        static_cast<size_t>(length)) == static_cast<size_t>(length);
}

static void clearExpiredWindow(uint32_t timestamp) {
    if (!window.hasGap(timestamp)) return;
    resetForLinkChange();
    if (serialConnected) Serial.println("# DATA_GAP");
}

static void acceptSample(const Lab3::Sample& sample) {
    clearExpiredWindow(sample.timeMs);
    const float values[MOTION_CHANNEL_COUNT] = {
        sample.ax, sample.ay, sample.az, sample.gx, sample.gy, sample.gz
    };
    if (!writeSample(sample.timeMs, values) && serialConnected) serialGapPending = true;

    float features[MOTION_FEATURE_COUNT];
    if (!window.add(sample.timeMs, values, features)) return;

    const int predicted = predictMotion(features);
    lastPrediction = MODEL_TRAINED && predicted >= 0 && predicted < 3 ? predicted : -1;
    hasResult = true;
    if (serialConnected || WirelessStream::connected()) {
        char line[40];
        snprintf(line, sizeof(line), "RESULT,%d,%lu\n", lastPrediction, static_cast<unsigned long>(sample.timeMs));
        if (serialConnected && !serialGapPending) Serial.print(line);
        WirelessStream::publish(line);
    }
}

static void showStatus() {
    if (!displayReady) return;
    Lab3::clearDisplay();
    Lab3::textLine(0, "EPL428 / IMU");
    Lab3::textLine(1, MODEL_TRAINED ? "MODEL READY" : "NO TRAINED MODEL");
    char line[22];
    if (!imuReady) {
        Lab3::textLine(2, "IMU STARTUP ERROR");
        Lab3::textLine(3, "Check Serial Monitor");
    } else if (!window.hasSample()) {
        Lab3::textLine(2, "NO FRESH IMU DATA");
        Lab3::textLine(3, "Waiting for samples");
    } else {
        snprintf(line, sizeof(line), "Samples: %u/%u",
                 static_cast<unsigned>(window.count()), static_cast<unsigned>(MOTION_WINDOW_SIZE));
        Lab3::textLine(2, line);
        if (!MODEL_TRAINED) {
            Lab3::textLine(3, "Data collection");
        } else if (!hasResult) {
            Lab3::textLine(3, "Awaiting window");
        } else if (lastPrediction < 0) {
            Lab3::textLine(3, "PREDICTION ERROR");
        } else {
            snprintf(line, sizeof(line), "Last: %s", MODEL_LABELS[lastPrediction]);
            Lab3::textLine(3, line);
        }
    }
    if (WirelessStream::connected()) Lab3::textLine(4, "Wi-Fi game linked");
    else if (serialConnected) Lab3::textLine(4, "USB Serial: 115200");
    else if (WirelessStream::available()) Lab3::textLine(4, "Wi-Fi: OrbitMaze");
    else Lab3::textLine(4, "USB disconnected");
    Lab3::sendDisplay();
}

void setup() {
    boardReady = Lab3::initBoard();
    // The lab configuration uses hardware USB CDC. Bound the wait when the host stops reading.
    Serial.setTxTimeoutMs(15);
    if (boardReady) {
        displayReady = Lab3::initDisplay();
        imuReady = Lab3::initIMU();
    }
    snprintf(statusLine, sizeof(statusLine), "STATUS,imu1,%s,%u,%u,%u\n", MODEL_RUN_ID,
             static_cast<unsigned>(boardReady), static_cast<unsigned>(imuReady),
             static_cast<unsigned>(displayReady));
    if (imuReady && MODEL_TRAINED) WirelessStream::begin();
    showStatus();
}

void loop() {
    serviceSerial();
    WirelessStream::service(statusLine);
    const uint32_t now = millis();
    clearExpiredWindow(now);
    if (imuReady && static_cast<uint32_t>(now - lastPoll) >= Lab3::POLL_MS) {
        lastPoll = now;
        Lab3::Sample sample;
        if (Lab3::readSample(sample)) acceptSample(sample);
    }
    if (static_cast<uint32_t>(now - lastDisplayUpdate) >= Lab3::OUTPUT_MS) {
        lastDisplayUpdate = now;
        showStatus();
    }
    delay(1);
}

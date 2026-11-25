#include "WirelessStream.h"

#include <WiFi.h>
#include <lwip/sockets.h>
#include <string.h>

namespace WirelessStream {
namespace {
constexpr uint16_t PORT = 8765;
constexpr char NETWORK[] = "OrbitMaze";
constexpr char DEMO_PASSWORD[] = "orbit-maze-428";
WiFiServer server(PORT, 1);
WiFiClient peer;
bool ready = false;
bool hasPeer = false;
uint32_t lastAccept = 0;

void disconnect() {
    peer.stop();
    hasPeer = false;
}
}

bool begin() {
    if (!WiFi.mode(WIFI_AP) || !WiFi.softAP(NETWORK, DEMO_PASSWORD, 1, false, 1)) return false;
    server.begin();
    server.setNoDelay(true);
    ready = static_cast<bool>(server);
    if (!ready) WiFi.softAPdisconnect(true);
    return ready;
}

void service(const char* statusLine) {
    if (!ready) return;
    const uint32_t now = millis();
    if (now - lastAccept < 50) return;
    lastAccept = now;
    if (hasPeer && peer.connected()) return;
    disconnect();
    peer = server.accept();
    hasPeer = static_cast<bool>(peer);
    if (hasPeer) publish(statusLine);
}

void publish(const char* line, size_t length) {
    if (!hasPeer) return;
    // A slow peer is disconnected rather than blocking IMU sampling or queuing stale gestures.
    if (send(peer.fd(), line, length, MSG_DONTWAIT) != static_cast<int>(length)) disconnect();
}

void publish(const char* line) {
    publish(line, strlen(line));
}

bool available() { return ready; }
bool connected() { return hasPeer; }
}

#pragma once
#include "Lab3Config.h"
#include <SPI.h>

namespace Lab3 {
extern SensorQMI8658 qmi;
extern SPIClass SDSPI;
struct Sample {
    float ax=0, ay=0, az=0; // units: g, not m/s^2
    float gx=0, gy=0, gz=0; // units: degrees/second, not angle
    uint32_t timeMs=0;
    bool valid=false;
};
bool initBoard();
bool initIMU();
void scanI2C();
bool readSample(Sample &out);
bool isFresh(const Sample &sample, uint32_t now);
bool initDisplay();
void clearDisplay();
void textLine(uint8_t line, const char *text);
void sendDisplay();
void drawError(const char *title, const char *detail);
bool startPedometer();
void serviceSerialReset();
void printSample(const Sample &sample);
}

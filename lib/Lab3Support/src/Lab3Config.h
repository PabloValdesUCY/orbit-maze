#pragma once
#include <Arduino.h>
#include <SensorQMI8658.hpp>

namespace Lab3 {
// Supreme V3.0 only. These pins are not for the older T-Beam ESP32 board.
constexpr int I2C_SDA_PIN=17, I2C_SCL_PIN=18;
constexpr int PMU_SDA_PIN=42, PMU_SCL_PIN=41;
constexpr int IMU_MOSI_PIN=35, IMU_MISO_PIN=37, IMU_SCK_PIN=36;
constexpr int IMU_CS_PIN=34, SD_CS_PIN=47;
// A7: instructor confirms on the physical class board; do not auto-identify by ACK.
constexpr uint8_t OLED_ADDRESS=0x3C;
constexpr uint32_t SERIAL_BAUD=115200;

// B1 / B2: edit ONE configuration item at a time; restore after the experiment.
constexpr auto ACC_RANGE=SensorQMI8658::ACC_RANGE_4G;
constexpr auto ACC_ODR=SensorQMI8658::ACC_ODR_125Hz;
constexpr auto ACC_LPF=SensorQMI8658::LPF_MODE_0;
constexpr auto GYRO_RANGE=SensorQMI8658::GYR_RANGE_64DPS;
constexpr auto GYRO_ODR=SensorQMI8658::GYR_ODR_112_1Hz;
constexpr auto GYRO_LPF=SensorQMI8658::LPF_MODE_3;
constexpr bool LPF_ENABLED=true;
constexpr bool SELF_TEST_ENABLED=false; // fifth argument in the bundled 0.1.0 API

// B3: host poll period is NOT the sensor output data rate.
constexpr uint32_t POLL_MS=10;
constexpr uint32_t OUTPUT_MS=250;
constexpr uint32_t STALE_MS=1000;
constexpr float STANDARD_G=9.80665f;
// D2: retained from supplied QMI8658_PedometerExample.ino; not calibrated.
constexpr uint16_t PED_SAMPLE_COUNT=0x007D;
constexpr uint16_t PED_PEAK_TO_PEAK=0x00CC;
constexpr uint16_t PED_PEAK=0x0066;
constexpr uint16_t PED_TIME_UP=0x00C8;
constexpr uint8_t PED_TIME_LOW=0x14;
constexpr uint8_t PED_ENTRY_COUNT=0x0A;
constexpr uint8_t PED_PRECISION=0x00;
constexpr uint8_t PED_PUBLISH_COUNT=0x04;
}

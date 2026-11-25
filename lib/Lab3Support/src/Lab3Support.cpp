#include "Lab3Support.h"
#include <Wire.h>
#include <XPowersLib.h>
#include <U8g2lib.h>
#include <math.h>

namespace Lab3 {
SensorQMI8658 qmi;
SPIClass SDSPI(HSPI);
static XPowersAXP2101 pmu(Wire1, PMU_SDA_PIN, PMU_SCL_PIN);
static U8G2_SH1106_128X64_NONAME_F_HW_I2C oled(U8G2_R0,U8X8_PIN_NONE);
static bool oledReady=false;

bool initBoard() {
    Serial.begin(SERIAL_BAUD);
    const uint32_t waitStart=millis();
    while (!Serial && millis()-waitStart<2000) { delay(10); }
    Serial.println("EPL428 Lab3 -- Supreme V3.0 / SensorLib 0.1.0");
    Wire1.begin(PMU_SDA_PIN,PMU_SCL_PIN);
    Wire1.setTimeOut(50);
    if (!pmu.init()) { Serial.println("ERROR: PMU AXP2101 not detected"); return false; }
    // Same sensor rails as the class setup; no charger or battery settings changed.
    pmu.setALDO1Voltage(3300); pmu.enableALDO1(); // OLED and sensor I2C rail
    pmu.setALDO2Voltage(3300); pmu.enableALDO2(); // IMU sensor rail
    pmu.setBLDO1Voltage(3300); pmu.enableBLDO1(); // shared-bus SD peripheral supply
    delay(50);
    Wire.begin(I2C_SDA_PIN,I2C_SCL_PIN);
    Wire.setTimeOut(50);
    pinMode(SD_CS_PIN,OUTPUT); digitalWrite(SD_CS_PIN,HIGH); // deselect SD
    pinMode(IMU_CS_PIN,OUTPUT); digitalWrite(IMU_CS_PIN,HIGH);
    SDSPI.begin(IMU_SCK_PIN,IMU_MISO_PIN,IMU_MOSI_PIN);
    Serial.println("PMU configured; SD CS=47 HIGH; IMU CS=34");
    return true;
}

void scanI2C() {
    Serial.print("I2C0 ACK addresses (not identities): ");
    for (uint8_t address=1; address<127; ++address) {
        Wire.beginTransmission(address);
        if (Wire.endTransmission()==0) Serial.printf("0x%02X ", address);
    }
    Serial.println();
    Serial.println("QMI8658 uses SPI here; it need not appear in this I2C scan.");
}

bool initIMU() {
    // Explicit SPI pins prevent accidental use of another board's default bus.
    if (!qmi.begin(IMU_CS_PIN,IMU_MOSI_PIN,IMU_MISO_PIN,IMU_SCK_PIN,SDSPI)) {
        Serial.println("ERROR: QMI8658 begin failed; check power/board/bus"); return false;
    }
    Serial.printf("QMI WHO_AM_I=0x%02X; expected 0x05\n", qmi.whoAmI());
    // 0 = success for these configuration functions in the bundled API.
    const int accResult=qmi.configAccelerometer(
        ACC_RANGE,ACC_ODR,ACC_LPF,LPF_ENABLED,SELF_TEST_ENABLED);
    const int gyroResult=qmi.configGyroscope(
        GYRO_RANGE,GYRO_ODR,GYRO_LPF,LPF_ENABLED,SELF_TEST_ENABLED);
    // Unlike configuration calls, disableSyncSampleMode returns true on success.
    if (accResult!=0 || gyroResult!=0 || !qmi.disableSyncSampleMode()) {
        Serial.println("ERROR: sensor configuration failed"); return false;
    }
    // SensorLib 0.1/0.2 invert the boolean register-write result in these
    // enable methods. Enable both, then verify the hardware bits directly.
    qmi.enableAccelerometer();
    qmi.enableGyroscope();
    if (!qmi.isEnableAccelerometer() || !qmi.isEnableGyroscope()) {
        Serial.println("ERROR: sensor enable failed"); return false;
    }
    Serial.println("IMU configured: LPF on; self-test OFF; asynchronous reads");
    return true;
}

bool readSample(Sample &out) {
    // SPI success alone cannot prove a responding device; ID is an extra sanity check.
    if (qmi.whoAmI()!=0x05 || !qmi.getDataReady()) return false;
    Sample next;
    const bool accOK=qmi.getAccelerometer(next.ax,next.ay,next.az);
    const bool gyroOK=(qmi.getGyroscope(next.gx,next.gy,next.gz)!=0);
    if (!accOK || !gyroOK || !isfinite(next.ax) || !isfinite(next.ay) ||
        !isfinite(next.az) || !isfinite(next.gx) || !isfinite(next.gy) || !isfinite(next.gz))
        return false;
    next.timeMs=millis(); next.valid=true; out=next;
    // This is a latest-register pair, not guaranteed simultaneous FIFO capture.
    return true;
}

bool isFresh(const Sample &s,uint32_t now) {
    return s.valid && static_cast<uint32_t>(now-s.timeMs)<=STALE_MS;
}

bool initDisplay() {
    Wire.beginTransmission(OLED_ADDRESS);
    if (Wire.endTransmission()!=0) {
        Serial.println("OLED did not ACK selected address; Serial path remains usable");
        return false;
    }
    oled.setI2CAddress(OLED_ADDRESS<<1); // U8g2 wants 8-bit shifted address
    oled.begin();
    oled.setFont(u8g2_font_6x12_tr); oled.setFontPosBaseline();
    oled.setDrawColor(1); oled.setFontMode(1);
    oledReady=true;
    clearDisplay(); textLine(0,"EPL428 / LAB 3"); textLine(2,"Verify visible text"); sendDisplay();
    Serial.println("OLED configured -- ACK is NOT proof of visible pixels.");
    return true;
}
void clearDisplay() { if (oledReady) oled.clearBuffer(); }
void textLine(uint8_t line,const char *text) {
    if (oledReady && line<5 && text) oled.drawStr(0,12+line*12,text);
}
void sendDisplay() { if (oledReady) oled.sendBuffer(); }
void drawError(const char *title,const char *detail) {
    clearDisplay();textLine(0,title);textLine(2,detail);sendDisplay();
}
void printSample(const Sample &s) {
    Serial.printf("t=%lu ax_g=%.3f ay_g=%.3f az_g=%.3f gx_dps=%.2f gy_dps=%.2f gz_dps=%.2f\n",
        static_cast<unsigned long>(s.timeMs),s.ax,s.ay,s.az,s.gx,s.gy,s.gz);
}

bool startPedometer() {
    // The old API returns 0 unconditionally here. Do NOT call that a validation pass.
    qmi.configPedometer(PED_SAMPLE_COUNT,PED_PEAK_TO_PEAK,PED_PEAK,
        PED_TIME_UP,PED_TIME_LOW,PED_ENTRY_COUNT,PED_PRECISION,PED_PUBLISH_COUNT);
    if (!qmi.enablePedometer()) { Serial.println("ERROR: pedometer enable failed");return false; }
    if (qmi.clearPedometerCounter()!=0) { Serial.println("ERROR: counter reset failed");return false; }
    Serial.println("Pedometer requested -- verify physical response, not just return codes.");
    Serial.println("Counter is a raw library value; 0 can also mean read failure.");
    Serial.println("Type r in Serial Monitor to request a counter reset.");
    return true;
}
void serviceSerialReset() {
    while (Serial.available()>0) {
        const char c=static_cast<char>(Serial.read());
        if (c=='r' || c=='R') {
            const int result=qmi.clearPedometerCounter();
            Serial.println(result==0 ? "Reset command sent; check next raw count" : "ERROR: reset command failed");
        }
    }
}
}

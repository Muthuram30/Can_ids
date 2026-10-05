#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_VL53L0X.h>
#include <SPI.h>
#include <mcp_can.h>

// ============================================================
// CAN IDs (must match Pi central app / project ID map)
// ============================================================
#define ID_TOF_DIST           0x120
#define ID_ULTRASONIC_DIST    0x121
#define ID_OBSTACLE_STATUS    0x122
#define ID_SENSOR_HEARTBEAT   0x013

// ============================================================
// I2C sensors
// ============================================================
#define I2C_SDA 21
#define I2C_SCL 22
Adafruit_MPU6050 mpu;
Adafruit_VL53L0X tof = Adafruit_VL53L0X();

// ============================================================
// Ultrasonic
// ============================================================
#define LEFT_TRIG   32
#define LEFT_ECHO   34
#define RIGHT_TRIG  33
#define RIGHT_ECHO  35

// ============================================================
// MCP2515
// ============================================================
#define CAN_CS   5
#define CAN_INT  4
#define CAN_SCK  18
#define CAN_MISO 19
#define CAN_MOSI 23
MCP_CAN CAN0(CAN_CS);

// ============================================================
// Timing — broadcast is decoupled from Serial debug so monitoring
// stays continuous regardless of what's printed
// ============================================================
const unsigned long SENSOR_BROADCAST_MS = 100;   // ~10 Hz continuous CAN broadcast
const unsigned long HEARTBEAT_MS        = 500;
const unsigned long DEBUG_PRINT_MS      = 1000;
const float OBSTACLE_THRESHOLD_CM       = 20.0;

unsigned long lastBroadcast  = 0;
unsigned long lastHeartbeat  = 0;
unsigned long lastDebugPrint = 0;

float readUltrasonicCM(byte trigPin, byte echoPin) {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  unsigned long duration = pulseIn(echoPin, HIGH, 30000);
  if (duration == 0) return -1;
  return (duration * 0.0343) / 2.0;
}

void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println();
  Serial.println("================================");
  Serial.println("ESP32 SENSOR ECU");
  Serial.println("================================");

  Wire.begin(I2C_SDA, I2C_SCL);

  if (!mpu.begin()) {
    Serial.println("MPU6050 NOT FOUND");
  } else {
    Serial.println("MPU6050 OK");
    mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
    mpu.setGyroRange(MPU6050_RANGE_500_DEG);
    mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
  }

  if (!tof.begin()) {
    Serial.println("ToF NOT FOUND");
  } else {
    Serial.println("ToF OK");
  }

  pinMode(LEFT_TRIG, OUTPUT);  pinMode(LEFT_ECHO, INPUT);
  pinMode(RIGHT_TRIG, OUTPUT); pinMode(RIGHT_ECHO, INPUT);
  digitalWrite(LEFT_TRIG, LOW);
  digitalWrite(RIGHT_TRIG, LOW);

  pinMode(CAN_INT, INPUT);
  SPI.begin(CAN_SCK, CAN_MISO, CAN_MOSI, CAN_CS);

  Serial.println("Initializing MCP2515...");
  while (CAN0.begin(MCP_ANY, CAN_500KBPS, MCP_8MHZ) != CAN_OK) {
    Serial.println("MCP2515 init failed, retrying...");
    delay(1000);
  }
  CAN0.setMode(MCP_NORMAL);

  Serial.println("MCP2515 OK -- broadcasting continuously on 0x120/0x121/0x122");
}

void loop() {
  unsigned long now = millis();

  // ---- continuous monitoring: read + broadcast every SENSOR_BROADCAST_MS ----
  if (now - lastBroadcast >= SENSOR_BROADCAST_MS) {
    lastBroadcast = now;

    float leftCM  = readUltrasonicCM(LEFT_TRIG, LEFT_ECHO);
    float rightCM = readUltrasonicCM(RIGHT_TRIG, RIGHT_ECHO);

    VL53L0X_RangingMeasurementData_t measure;
    tof.rangingTest(&measure, false);
    uint16_t tofMM = (measure.RangeStatus != 4) ? measure.RangeMilliMeter : 0xFFFF;

    // ToF distance -> 0x120 (2 bytes, little-endian mm; 0xFFFF = out of range)
    byte tofBuf[2] = { (byte)(tofMM & 0xFF), (byte)(tofMM >> 8) };
    CAN0.sendMsgBuf(ID_TOF_DIST, 0, 2, tofBuf);

    // Ultrasonic L/R -> 0x121 (4 bytes, little-endian, units of 0.1 cm; 0xFFFF = out of range)
    uint16_t leftMM10  = (leftCM  < 0) ? 0xFFFF : (uint16_t)(leftCM  * 10);
    uint16_t rightMM10 = (rightCM < 0) ? 0xFFFF : (uint16_t)(rightCM * 10);
    byte usBuf[4] = {
      (byte)(leftMM10 & 0xFF),  (byte)(leftMM10 >> 8),
      (byte)(rightMM10 & 0xFF), (byte)(rightMM10 >> 8)
    };
    CAN0.sendMsgBuf(ID_ULTRASONIC_DIST, 0, 4, usBuf);

    // Fused obstacle flags -> 0x122 (bit0=left near, bit1=right near, bit2=ToF near)
    byte flags = 0;
    if (leftCM  >= 0 && leftCM  < OBSTACLE_THRESHOLD_CM) flags |= 0x01;
    if (rightCM >= 0 && rightCM < OBSTACLE_THRESHOLD_CM) flags |= 0x02;
    if (tofMM != 0xFFFF && tofMM < (uint16_t)(OBSTACLE_THRESHOLD_CM * 10)) flags |= 0x04;
    byte obsBuf[1] = { flags };
    CAN0.sendMsgBuf(ID_OBSTACLE_STATUS, 0, 1, obsBuf);
  }

  // ---- heartbeat ----
  if (now - lastHeartbeat >= HEARTBEAT_MS) {
    lastHeartbeat = now;
    byte hb[1] = {1};
    CAN0.sendMsgBuf(ID_SENSOR_HEARTBEAT, 0, 1, hb);
  }

  // ---- light debug print, decoupled from the broadcast rate ----
  if (now - lastDebugPrint >= DEBUG_PRINT_MS) {
    lastDebugPrint = now;
    Serial.println("[SENSOR ECU] broadcasting (0x120/0x121/0x122) @ 10Hz");
  }
}

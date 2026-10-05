#include <SPI.h>
#include <mcp_can.h>

// ============================================================
// CAN IDs (must match Pi central app / project ID map)
// ============================================================
#define ID_MOTOR_CMD        0x100   // Pi -> this node
#define ID_MOTOR_STATUS      0x101  // this node -> Pi
#define ID_MOTOR_HEARTBEAT   0x011

// ============================================================
// MCP2515 (VSPI on ESP32)
// ============================================================
#define CAN_CS   5
#define CAN_INT  4
#define CAN_SCK  18
#define CAN_MISO 19
#define CAN_MOSI 23

MCP_CAN CAN0(CAN_CS);

// ============================================================
// MOTOR DRIVER PINS (unchanged from original)
// ============================================================
#define LF_IN1 25
#define LF_IN2 26
#define LR_IN1 27
#define LR_IN2 32
#define RF_IN1 33
#define RF_IN2 13
#define RR_IN1 14
#define RR_IN2 2

char currentCmd = 'S';
unsigned long lastCmdRxTime  = 0;
unsigned long lastHeartbeat  = 0;
unsigned long lastStatusSend = 0;

const unsigned long CMD_FAILSAFE_MS = 500;  // stop motors if Pi/CAN link goes quiet
const unsigned long HEARTBEAT_MS    = 500;
const unsigned long STATUS_MS       = 200;

void stopMotors() {
  digitalWrite(LF_IN1, LOW); digitalWrite(LF_IN2, LOW);
  digitalWrite(LR_IN1, LOW); digitalWrite(LR_IN2, LOW);
  digitalWrite(RF_IN1, LOW); digitalWrite(RF_IN2, LOW);
  digitalWrite(RR_IN1, LOW); digitalWrite(RR_IN2, LOW);
}
void forward() {
  digitalWrite(LF_IN1, HIGH); digitalWrite(LF_IN2, LOW);
  digitalWrite(LR_IN1, HIGH); digitalWrite(LR_IN2, LOW);
  digitalWrite(RF_IN1, HIGH); digitalWrite(RF_IN2, LOW);
  digitalWrite(RR_IN1, HIGH); digitalWrite(RR_IN2, LOW);
}
void backward() {
  digitalWrite(LF_IN1, LOW); digitalWrite(LF_IN2, HIGH);
  digitalWrite(LR_IN1, LOW); digitalWrite(LR_IN2, HIGH);
  digitalWrite(RF_IN1, LOW); digitalWrite(RF_IN2, HIGH);
  digitalWrite(RR_IN1, LOW); digitalWrite(RR_IN2, HIGH);
}
void turnLeft() {
  digitalWrite(LF_IN1, LOW);  digitalWrite(LF_IN2, HIGH);
  digitalWrite(LR_IN1, LOW);  digitalWrite(LR_IN2, HIGH);
  digitalWrite(RF_IN1, HIGH); digitalWrite(RF_IN2, LOW);
  digitalWrite(RR_IN1, HIGH); digitalWrite(RR_IN2, LOW);
}
void turnRight() {
  digitalWrite(LF_IN1, HIGH); digitalWrite(LF_IN2, LOW);
  digitalWrite(LR_IN1, HIGH); digitalWrite(LR_IN2, LOW);
  digitalWrite(RF_IN1, LOW);  digitalWrite(RF_IN2, HIGH);
  digitalWrite(RR_IN1, LOW);  digitalWrite(RR_IN2, HIGH);
}

void applyCommand(char c) {
  currentCmd = c;
  switch (c) {
    case 'F': forward();   break;
    case 'B': backward();  break;
    case 'L': turnLeft();  break;
    case 'R': turnRight(); break;
    default:  stopMotors(); currentCmd = 'S'; break;
  }
}

void setup() {
  Serial.begin(115200);

  pinMode(LF_IN1, OUTPUT); pinMode(LF_IN2, OUTPUT);
  pinMode(LR_IN1, OUTPUT); pinMode(LR_IN2, OUTPUT);
  pinMode(RF_IN1, OUTPUT); pinMode(RF_IN2, OUTPUT);
  pinMode(RR_IN1, OUTPUT); pinMode(RR_IN2, OUTPUT);
  stopMotors();

  pinMode(CAN_INT, INPUT);
  SPI.begin(CAN_SCK, CAN_MISO, CAN_MOSI, CAN_CS);

  Serial.println("[MOTOR ECU] Initializing MCP2515...");
  while (CAN0.begin(MCP_ANY, CAN_500KBPS, MCP_8MHZ) != CAN_OK) {
    Serial.println("[MOTOR ECU] MCP2515 init failed, retrying...");
    delay(1000);
  }
  CAN0.setMode(MCP_NORMAL);
  Serial.println("[MOTOR ECU] Ready. Listening for CAN motor commands on 0x100.");
  lastCmdRxTime = millis();
}

void loop() {
  // ---- receive drive command from Pi ----
  if (CAN0.checkReceive() == CAN_MSGAVAIL) {
    unsigned long rxId;
    byte len;
    byte buf[8];
    CAN0.readMsgBuf(&rxId, &len, buf);
    if (rxId == ID_MOTOR_CMD && len >= 1) {
      applyCommand((char)buf[0]);
      lastCmdRxTime = millis();
    }
  }

  // ---- failsafe: stop if the Pi/CAN link goes quiet ----
  if (millis() - lastCmdRxTime > CMD_FAILSAFE_MS && currentCmd != 'S') {
    stopMotors();
    currentCmd = 'S';
    Serial.println("[MOTOR ECU] Failsafe: command timeout, stopping.");
  }

  // ---- status back to Pi ----
  if (millis() - lastStatusSend >= STATUS_MS) {
    lastStatusSend = millis();
    byte data[1] = { (byte)currentCmd };
    CAN0.sendMsgBuf(ID_MOTOR_STATUS, 0, 1, data);
  }

  // ---- heartbeat ----
  if (millis() - lastHeartbeat >= HEARTBEAT_MS) {
    lastHeartbeat = millis();
    byte hb[1] = {1};
    CAN0.sendMsgBuf(ID_MOTOR_HEARTBEAT, 0, 1, hb);
  }
}

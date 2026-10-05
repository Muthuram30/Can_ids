#include <SPI.h>
#include <mcp_can.h>

// ============================================================
// CAN IDs (must match Pi central app / project ID map)
// ============================================================
#define ID_LOCK_CMD            0x140  // Pi -> this node
#define ID_LOCK_STATUS          0x141 // this node -> Pi
#define ID_SECURITY_HEARTBEAT   0x014

// ============================================================
// Solenoid (active-low relay: LOW = ON, HIGH = OFF)
// ============================================================
#define SOLENOID 3

// ============================================================
// MCP2515
// ============================================================
#define CAN_CS   5
#define CAN_INT  4
#define CAN_SCK  18
#define CAN_MISO 19
#define CAN_MOSI 23
MCP_CAN CAN0(CAN_CS);

bool solenoidOn = false;
unsigned long lastHeartbeat  = 0;
unsigned long lastStatusSend = 0;
const unsigned long HEARTBEAT_MS = 500;
const unsigned long STATUS_MS    = 200;

void solenoidON() {
  digitalWrite(SOLENOID, LOW);
  solenoidOn = true;
  Serial.println("[SECURITY ECU] SOLENOID: ON");
}

void solenoidOFF() {
  digitalWrite(SOLENOID, HIGH);
  solenoidOn = false;
  Serial.println("[SECURITY ECU] SOLENOID: OFF");
}

void setup() {
  Serial.begin(115200);

  pinMode(SOLENOID, OUTPUT);
  solenoidOFF();

  pinMode(CAN_INT, INPUT);
  SPI.begin(CAN_SCK, CAN_MISO, CAN_MOSI, CAN_CS);

  Serial.println();
  Serial.println("================================");
  Serial.println("ESP32 SECURITY ECU");
  Serial.println("MCP2515 INITIALIZATION");
  Serial.println("================================");

  while (CAN0.begin(MCP_ANY, CAN_500KBPS, MCP_8MHZ) != CAN_OK) {
    Serial.println("[SECURITY ECU] MCP2515 init failed, retrying...");
    delay(1000);
  }
  CAN0.setMode(MCP_NORMAL);

  Serial.println("[SECURITY ECU] Ready. Listening for CAN lock commands on 0x140.");
}

void loop() {
  // ---- receive lock command from Pi ----
  if (CAN0.checkReceive() == CAN_MSGAVAIL) {
    unsigned long rxId;
    byte len;
    byte buf[8];
    CAN0.readMsgBuf(&rxId, &len, buf);
    if (rxId == ID_LOCK_CMD && len >= 1) {
      if (buf[0]) solenoidON(); else solenoidOFF();
    }
  }

  // ---- status back to Pi ----
  if (millis() - lastStatusSend >= STATUS_MS) {
    lastStatusSend = millis();
    byte data[1] = { (byte)(solenoidOn ? 1 : 0) };
    CAN0.sendMsgBuf(ID_LOCK_STATUS, 0, 1, data);
  }

  // ---- heartbeat ----
  if (millis() - lastHeartbeat >= HEARTBEAT_MS) {
    lastHeartbeat = millis();
    byte hb[1] = {1};
    CAN0.sendMsgBuf(ID_SECURITY_HEARTBEAT, 0, 1, hb);
  }
}

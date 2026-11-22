# Hardware and CAN reference

All supplied ESP32 sketches use SPI SCK=18, MISO=19, MOSI=23, MCP2515 CS=5 and INT=4. Confirm each sketch before wiring. They call `CAN_500KBPS` with `MCP_8MHZ`; this must match the crystal on each ESP32-side CAN module. The Pi overlay must independently match the Pi-side module.

| CAN ID | Meaning | Direction |
|---|---|---|
| `0x010` | Pi heartbeat | Pi → bus |
| `0x011` | Motor heartbeat | Motor → Pi |
| `0x013` | Sensor heartbeat | Sensor → Pi |
| `0x014` | Security heartbeat | Security → Pi |
| `0x100` | ASCII `F/B/L/R/S` motor command | Pi → Motor |
| `0x101` | Motor status | Motor → Pi |
| `0x120` | ToF distance, uint16 little-endian mm | Sensor → Pi |
| `0x121` | Left/right ultrasound, two little-endian uint16 values in 0.1 cm units | Sensor → Pi |
| `0x122` | Obstacle bit flags | Sensor → Pi |
| `0x140` | Lock command, 0/1 | Pi → Security |
| `0x141` | Lock status, 0/1 | Security → Pi |

Unknown distance is `0xFFFF`. Normal heartbeat interval is 500 ms. The Pi marks a node offline after two seconds without an expected node frame. The motor firmware stops after 500 ms without a drive frame. The gateway's browser timeout is separate: it stops sending a non-stop command when fresh joystick input stops, while still providing CAN keepalives during an active browser hold.

## Firmware upload

Use Arduino IDE with the ESP32 board support package and `mcp_can` library. The Sensor sketch additionally includes `Wire.h`, `Adafruit_MPU6050`, `Adafruit_Sensor` and `Adafruit_VL53L0X`; install the corresponding Adafruit libraries and their dependencies. For each upload, create a separate sketch folder such as `Motor_ECU_Node/Motor_ECU_Node.ino`, select the board and COM port and compile/upload. The three `.ino` files must not be compiled together in one Arduino sketch.

Do not assume generic 5 V MCP2515/TJA1050 boards accept 3.3 V supplies or return safe logic levels. Use compatible modules/level conversion. Keep motor/solenoid supply currents out of MCU GPIO and provide suitable drivers, flyback protection and common ground.

## Hardware-free Linux CAN smoke test

On a Linux machine/Pi without physical CAN attached:

```bash
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan
sudo ip link set vcan0 up
```

Set `CAN_CHANNEL=vcan0`, `CAN_BACKEND=socketcan` in `.env`, restart the app, then send a sensor frame from a second terminal:

```bash
cansend vcan0 120#E803
```

The dashboard should show 1000 mm. This checks software decode and plumbing, not the physical bus or sensors. Do not run arbitrary test frames on a vehicle network. For the Windows unit tests, `python-can` uses its in-process virtual backend, so no Linux driver is required.

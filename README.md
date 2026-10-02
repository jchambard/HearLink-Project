# HearLink

**Wearable spatial-sound awareness for Deaf and hard-of-hearing users.**

HearLink is a two-part system built at StarkHacks. A collar-mounted ESP32-S3 captures audio from a four-microphone ring and head yaw from an IMU, then streams it over Wi-Fi to a host computer. The host beamforms the array to find where sounds are coming from, classifies them with Google's YAMNet, sorts them into **Dangerous / Social / Ambient**, and sends feedback back to the wearer: a directional icon on a head-mounted OLED compass and a haptic buzz from the collar buzzer closest to the sound.

```
                    ┌────────────────────────────────────────────┐
   4× I²S MEMS mics │  ESP32-S3 (collar)                         │  Wi-Fi SoftAP "HearLink"
   MPU-6050 gyro ──►│  audio_capture ─► udp_tx ──────────────────┼──────────► UDP :5005 ──┐
   4× piezo buzzers◄┤  buzzer_control ◄─ udp_rx ◄────────────────┼◄────────── UDP :5006 ◄─┤
   SSD1306 OLED (HUD)◄┤ display        ◄─┘                        │                        │
                    └────────────────────────────────────────────┘                        │
                                                                                          │
                    ┌────────────────────────────────────────────────────────────────────┐│
                    │  Host (Python 3)                                                   ││
                    │  udp_receiver ─► buffer_manager ─► beamformer ─► yamnet ─► mapper  │◄┘
                    │        │                                                 │         │
                    │        └─► yaw_integrator ──────────► event_router / display_mgr ──┼──► commands
                    └────────────────────────────────────────────────────────────────────┘
```

---

## Table of contents

1. [Repository layout](#repository-layout)
2. [Hardware](#hardware)
3. [Firmware (ESP32-S3)](#firmware-esp32-s3)
4. [Host software (Python)](#host-software-python)
5. [Wire protocol](#wire-protocol)
6. [Processing pipeline](#processing-pipeline)
7. [Coordinate frames](#coordinate-frames)
8. [Testing](#testing)
9. [Configuration reference](#configuration-reference)
10. [Known issues and limitations](#known-issues-and-limitations)
11. [Further documentation](#further-documentation)

---

## Repository layout

```
.
├── hearlink-firmware/            ESP-IDF project for the ESP32-S3 collar unit
│   ├── CMakeLists.txt
│   ├── sdkconfig.defaults        Wi-Fi / lwIP / FreeRTOS tuning
│   └── main/
│       ├── main.c                Boot sequence, task launch, heartbeat + status LED
│       ├── config.h              All pins, ports, constants, task priorities
│       ├── audio_capture.c/.h    Dual I²S RX → 4-channel AudioBuffer, calibration delays
│       ├── imu_driver.c/.h       MPU-6050 over I²C, 100 Hz yaw-rate poll
│       ├── network.c/.h          SoftAP, UDP TX (audio+IMU) and RX (commands)
│       ├── buzzer_control.c/.h   LEDC PWM patterns for 4 piezo buzzers
│       ├── display.c/.h          Bare-metal SSD1306 driver, 12×12 icon ring
│       ├── calibration.c/.h      Per-channel sample offsets persisted in NVS
│       └── test_mode.c/.h        On-device self-tests triggered over UDP
│
├── hearlink/host/                Python host application
│   ├── requirements.txt
│   ├── setup.py
│   ├── pytest.ini
│   ├── config/
│   │   ├── audio_config.yaml       Mic geometry, beamformer, processing cadence
│   │   ├── network_config.yaml     ESP32 IP and UDP ports
│   │   └── yamnet_categories.yaml  YAMNet class → category mapping + thresholds
│   ├── src/
│   │   ├── main.py                 HearLinkHost orchestrator (asyncio)
│   │   ├── network/                udp_receiver.py, command_sender.py
│   │   ├── audio/                  buffer_manager.py, beamformer.py, audio_utils.py
│   │   ├── imu/                    yaw_integrator.py
│   │   ├── classification/         yamnet_classifier.py, category_mapper.py
│   │   ├── feedback/               event_router.py, display_manager.py
│   │   └── utils/                  logger.py
│   ├── scripts/smoke_test.py       End-to-end hardware check
│   └── tests/                      pytest suite (unit + one slow integration test)
│
├── components/u8g2/              Vendored u8g2 graphics library (currently unused, see notes)
│
├── host-firmware-overview.md     Protocol reference: packets, commands, lifecycle
├── host_implementation_plan.md   Phased build plan for the host, with verification steps
└── host_implementation_guide.md  Long-form implementation guide (contains known errata)
```

---

## Hardware

### Bill of materials

| Part | Role | Interface |
|---|---|---|
| ESP32-S3-DevKitC-1 | Collar controller, Wi-Fi SoftAP | — |
| 4× I²S MEMS microphones (24-bit) | Mic ring at 90° spacing, ~9.5 cm radius | I²S0 (front/right), I²S1 (back/left) |
| MPU-6050 | Head yaw rate (gyro only) | I²C @ 400 kHz, addr `0x68` |
| SSD1306 128×64 OLED | Head-mounted compass HUD | I²C, addr `0x3C` |
| 4× piezo buzzers + driver boards | Directional haptics on collar | LEDC PWM, 200 Hz |
| On-board WS2812 LED (GPIO 48) | Boot / ready / overload status | RMT |

### Pin map (from `hearlink-firmware/main/config.h`)

| Signal | GPIO |
|---|---|
| I²S0 BCLK / LRCLK / SD | 4 / 5 / 6 |
| I²S1 BCLK / LRCLK / SD | 7 / 15 / 16 |
| I²C SDA / SCL (IMU + OLED) | 8 / 9 |
| Buzzer 0 (front) / 1 (right) / 2 (back) / 3 (left) | 1 / 2 / 10 / 11 |
| Status LED | 48 |

### Physical placement

- **Mics and buzzers** are on the collar. Beamformer output and buzzer commands are therefore in the **collar frame**.
- **IMU and OLED** are on the head. The HUD renders a heading-up compass, so icon positions are **head-relative**.
- The OLED is mounted rotated 90° clockwise. The firmware compensates in `direction_to_xy` so that direction byte `0` draws at the physical top of the ring.

Channel order everywhere in the system is `ch0 = Front, ch1 = Right, ch2 = Back, ch3 = Left`.

---

## Firmware (ESP32-S3)

### Toolchain

- ESP-IDF **5.3** (the checked-in `sdkconfig` was generated by 5.3.0)
- Target: `esp32s3`
- Managed dependency: `espressif/led_strip ^2.5.5` (resolved via `main/idf_component.yml`)

### Build and flash

```bash
cd hearlink-firmware
. $IDF_PATH/export.sh
idf.py set-target esp32s3
idf.py build
idf.py -p /dev/cu.usbmodem* flash monitor
```

On a clean checkout the IDF Component Manager downloads `led_strip` automatically during the first build.

### Boot sequence

1. Initialise NVS (erased and re-created if the partition layout changed).
2. Status LED dim green.
3. Bring up the shared I²C bus, then I²S capture, IMU, buzzers, OLED. A missing IMU or OLED logs a warning and continues; everything else is fatal.
4. Load calibration offsets from NVS and apply them to the audio capture ring buffer.
5. Start Wi-Fi SoftAP `HearLink` at `192.168.4.1`.
6. Launch tasks: audio capture and UDP TX on core 1, everything else on core 0.
7. Status LED bright green, then a 1 Hz heartbeat blink. A red flash means audio frames were dropped in the last second because the host could not keep up.

### Status LED

| Colour | Meaning |
|---|---|
| Dim green | Booting |
| Amber | Single-mic bring-up mode (`MIC_TEST_BOOT_MODE=1`) |
| Blinking green | Running normally |
| Red flash | Audio queue overflow, frames dropped |

### Runtime tasks

| Task | Core | Priority | Job |
|---|---|---|---|
| audio_capture | 1 | 5 | Deinterleave both I²S buses into a 4-channel 160-sample buffer every 10 ms |
| udp_tx | 1 | 4 | Split each buffer into two 1292-byte datagrams, send to the host |
| udp_rx | 0 | 3 | Parse 4-byte commands, learn host IP, dispatch to queues |
| imu_poll | 0 | 3 | Read gyro at 100 Hz into a shared variable |
| buzzer_control | 0 | 2 | Run buzz patterns on the LEDC channels |
| display_update | 0 | 1 | Draw icon ring on the OLED |
| test_mode | 0 | 1 | Run one self-test at a time when notified |

### On-device self-tests

Any host on the AP can trigger these by sending a 4-byte command to port 5006. Results print to the serial monitor.

| Command | What it does |
|---|---|
| `CMD_TEST_BUZZERS` (`0x11`) | Cycle each buzzer at 50% for 1 s |
| `CMD_TEST_DISPLAY` (`0x12`) | Rotate a warning icon around the ring |
| `CMD_TEST_MICS` (`0x13`) | Print per-channel RMS for 10 s |
| `CMD_TEST_IMU` (`0x14`) | Print raw yaw rate every 100 ms for 10 s |
| `CMD_TEST_MICS_INDIV` (`0x15`) | Cycle mics one at a time with a live level bar |
| `CMD_TEST_BUZZER_SOLO` (`0x16`) | Fire one buzzer at 100% for 10 s; `direction` = buzzer index |

For wiring bring-up without any host, set `MIC_TEST_BOOT_MODE` to `1` in `config.h`. The device skips networking and loops through each mic with a serial banner.

### Firmware notes

- `display.c` talks to the SSD1306 directly over I²C. The vendored `components/u8g2` library is not referenced by `main/CMakeLists.txt` and is not inside the firmware project directory, so it is not compiled. It is kept in the tree as an option for richer rendering later.
- Some header comments still mention "8 buzzers" from an earlier design. `NUM_BUZZERS` is **4** and that is the ground truth.
- The current working tree has an uncommitted change in `imu_driver.c` that reads the gyro **X** register instead of Z. This matches how the IMU is physically mounted on the headset. Confirm the axis against your own mounting before flashing.

---

## Host software (Python)

### Requirements

- Python **3.10 or newer**. The committed virtualenv was created with 3.13.7 on macOS arm64.
- TensorFlow 2.16+ (universal wheels, no `tensorflow-macos` needed).
- Network access on first run so TensorFlow Hub can download YAMNet (about 17 MB, cached afterwards).

### Install

```bash
cd hearlink/host
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Run

1. Power the collar unit and wait for the blinking green LED.
2. Join the Wi-Fi network `HearLink` with password `hearlink2025`.
3. Start the host:

```bash
cd hearlink/host
source venv/bin/activate
python src/main.py
```

What happens at startup:

- YAMNet loads (roughly 5 s cold, logged).
- The UDP receiver binds port 5005.
- The host sends a `CMD_TEST_MODE` packet so the firmware learns the host IP and starts streaming.
- The processing loop and the display update loop run concurrently under asyncio.
- `Ctrl-C` clears the HUD, closes sockets, and exits cleanly.

Detections are logged at INFO level, for example:

```
Sound: Siren (DANGEROUS) at 90° (head-rel 90°) conf=0.71
```

### Hardware smoke test

With the ESP32 powered and the host joined to the AP:

```bash
cd hearlink/host
venv/bin/python scripts/smoke_test.py
```

The script registers with the device, counts packets for 2 s, validates packet structure and sequence ordering, then walks icons and buzzers around the four compass points and asks you to confirm what you saw and felt. It prints `SMOKE TEST: PASS` or `FAIL`.

---

## Wire protocol

Full detail lives in [`host-firmware-overview.md`](host-firmware-overview.md). The essentials:

### Network

| Parameter | Value |
|---|---|
| SSID / password | `HearLink` / `hearlink2025` (WPA2-PSK, channel 1) |
| ESP32 address | `192.168.4.1` (static), DHCP for up to 4 clients |
| ESP32 → host | UDP **5005**, audio + IMU stream |
| Host → ESP32 | UDP **5006**, 4-byte commands |

There is no handshake or keepalive. The firmware starts streaming to whichever address last sent it a command, and keeps streaming until power-off.

### Inbound: `AudioIMUSubPacket` (1292 bytes, little-endian, packed)

| Field | Type | Meaning |
|---|---|---|
| `seq` | `uint32` | Increments once per 160-sample buffer |
| `timestamp_us` | `uint32` | ESP32 uptime in microseconds |
| `imu_yaw_rate` | `int16` | Raw gyro LSB, ±250 °/s range, 131 LSB per °/s |
| `sub_seq` | `uint8` | `0` = samples 0–79, `1` = samples 80–159 |
| `pad` | `uint8` | Always 0 |
| `audio[4][80]` | `int32` | 4 channels × 80 samples, 24-bit data left-justified |

Each 10 ms buffer is sent as two datagrams sharing a `seq`, so the stream is 200 packets per second. Sub-packets can arrive out of order or be lost independently. The firmware pre-applies calibration delays, so channels arrive time-aligned.

Python struct format: `'<IIhBB' + 'i' * 320`.

### Outbound: `Command` (4 bytes)

```
[type, direction, category, pattern]
```

| `type` | Name | `direction` | `category` | `pattern` |
|---|---|---|---|---|
| `0x01` | `CMD_DISPLAY_ICON` | 0–255 → 0–360° | 0/1/2 | `IconType` |
| `0x02` | `CMD_FIRE_BUZZER` | 0–255 → 0–360° | 0/1/2 (firmware picks intensity) | `BuzzerPattern` |
| `0x03` | `CMD_CLEAR_ALL` | — | — | — |
| `0x04` | `CMD_CALIBRATE` | — | — | — |
| `0x05` | `CMD_SET_CALIBRATION` | channel 0–3 | — | signed offset as `uint8` |
| `0x10`–`0x16` | `CMD_TEST_*` | see self-tests | — | — |

Direction byte: `0` = front, `64` = right, `128` = back, `192` = left. Host conversion is `int((deg % 360) * 256 / 360) & 0xFF`.

Buzzer patterns: `0` off, `1` continuous, `2` fast pulse (200 ms), `3` slow pulse (500 ms), `4` double tap.

Buzzer intensity is chosen by the firmware from the category byte: Dangerous 100, Social 70, Ambient 40, mapped onto a PWM duty capped at 50%.

Example, buzz toward the right for a dangerous sound with a double tap:

```
[0x02, 0x40, 0x00, 0x04]
```

---

## Processing pipeline

Every `process_interval_sec` (default 0.5 s) the host runs the following on the most recent `window_duration_sec` (default 1.0 s) of audio.

1. **Reassembly** (`audio/buffer_manager.py`). Pairs sub-packets by `seq` into `(4, 160)` buffers, normalises int32 to float32 in [-1, 1], and writes into a 2 s circular buffer. Incomplete buffers older than 5 sequence numbers are evicted so lost packets cannot leak memory.

2. **Beamforming** (`audio/beamformer.py`). Delay-and-sum over 24 steering angles using the mic ring geometry from `audio_config.yaml`. Per-beam energy is smoothed with a 3-tap moving average, the top 3 peaks are kept, and anything below twice the median energy is discarded. Each detection returns the steered mono audio so the classifier does not have to re-steer.

3. **Classification** (`classification/yamnet_classifier.py`). Each beam's audio goes through YAMNet (521 AudioSet classes). Frame scores are averaged over the window and the top 5 classes are returned.

4. **Category mapping** (`classification/category_mapper.py`). Classes are matched case-insensitively against `yamnet_categories.yaml` and kept only if above that category's confidence threshold. The best surviving match becomes the event's category.

5. **Yaw integration** (`imu/yaw_integrator.py`). The first 200 samples (2 s) after startup set the gyro bias; the user should hold still. Thereafter yaw rate is integrated at a fixed 100 Hz and wrapped to [0, 360). Only `sub_seq == 0` packets feed the integrator to avoid double-counting.

6. **Feedback**.
   - `feedback/event_router.py` sorts events by category priority then confidence, keeps the top 3, and fires a double-tap buzzer in the collar frame for categories enabled in `buzzer_preferences`.
   - `feedback/display_manager.py` keeps up to 3 active icons alive for 5 s and re-sends them at 10 Hz with head-relative angles, then clears the HUD when nothing remains.

Icon mapping: Dangerous → warning triangle, Social → speech bubble, Ambient → music note.

---

## Coordinate frames

| Thing | Frame | Why |
|---|---|---|
| Beamformer angle | Collar | Mics are on the collar |
| Buzzer command | Collar | Buzzers are on the collar; no yaw correction |
| HUD icon command | Head-relative | HUD is heading-up: `(collar_angle − head_yaw) mod 360` |

Zero yaw is defined as wherever the head was pointing when bias calibration finished. If the user starts the system while looking sideways, the compass will be offset by that angle until restart.

---

## Testing

### Unit tests (no hardware)

```bash
cd hearlink/host
venv/bin/pytest tests/ -m "not slow" -v
```

| Test file | Covers |
|---|---|
| `test_packet_parsing.py` | struct round-trip, malformed packet handling, direction byte encoding |
| `test_buffer.py` | sub-packet reassembly, TTL eviction, circular buffer wrap |
| `test_beamformer.py` | synthetic impulses from 0/90/180/270° resolve within ±15° |
| `test_yaw_integration.py` | bias calibration, integration, 360° wrap |
| `test_category_mapper.py` | threshold filtering, ordering, case-insensitivity |
| `test_event_router.py` | priority ordering, max concurrent events, buzzer preferences |

### Integration test (downloads YAMNet)

```bash
venv/bin/pytest -m slow -v
```

### Current status

Running the fast suite on this tree gives **47 passed, 5 failed**. The failures are stale tests, not pipeline regressions:

- Four `test_event_router.py` tests assert that the router calls `display_icon`. Icon rendering moved to `DisplayManager`, so the router now only fires buzzers. The tests need updating to match.
- `test_noise_only_no_detections` in `test_beamformer.py` expects white noise to yield zero detections. The current `2 × median` threshold occasionally lets one through. Either the threshold or the test tolerance needs tuning.

---

## Configuration reference

### `config/audio_config.yaml`

| Key | Default | Notes |
|---|---|---|
| `mic_array.radius_m` | `0.095` | Distance from ring centre to each mic |
| `mic_array.num_mics` | `4` | Fixed by firmware |
| `beamforming.num_beams` | `24` | 15° resolution |
| `beamforming.speed_of_sound_mps` | `343.0` | |
| `processing.window_duration_sec` | `1.0` | Audio fed to beamformer + YAMNet |
| `processing.process_interval_sec` | `0.5` | How often the loop runs |
| `imu.sample_rate_hz` | `100` | Must match firmware poll rate |
| `imu.calibration_duration_sec` | `2.0` | Hold-still period at startup |
| `buzzer_preferences.*` | dangerous only | Which categories trigger haptics |

### `config/network_config.yaml`

| Key | Default |
|---|---|
| `esp32_ip` | `192.168.4.1` |
| `rx_port` | `5005` |
| `tx_port` | `5006` |

### `config/yamnet_categories.yaml`

Lists of YAMNet class names under `dangerous`, `social`, `ambient`, plus a `confidence_thresholds` block (defaults 0.3 / 0.4 / 0.5). Add or remove class names freely; they must match YAMNet's class map spelling, matched case-insensitively.

---

## Known issues and limitations

- **Head yaw is not yet wired into the HUD.** `main.py` passes a constant `0.0` yaw provider to the display manager's update loop, so icons are drawn in the collar frame with a fixed 90° rotation offset. Replace it with `self.yaw_integrator.get_yaw` once the IMU axis is confirmed on hardware.
- **Startup does not wait for IMU calibration.** `_wait_for_calibration` exists but is not called from `run()`. Logged yaw will be zero for the first 2 s.
- **Yaw drifts.** Pure gyro integration has no absolute reference. Expect a few degrees of drift per minute; a `reset()` is available on the integrator but is not yet bound to any command.
- **No packet-loss concealment.** Missing sub-packets evict the whole 10 ms buffer rather than zero-filling.
- **Fixed 2 MB flash** in `sdkconfig`. If you move to a board with more flash, update `CONFIG_ESPTOOLPY_FLASHSIZE`.
- **The implementation guide contains errata.** `host_implementation_plan.md` lists five known bugs in `host_implementation_guide.md` (category byte values, 8 vs 4 buzzers, event-loop API, yaw applied to buzzers, unbounded pending map). The code follows the plan, not the guide, wherever they disagree.

---

## Further documentation

- [`host-firmware-overview.md`](host-firmware-overview.md) — authoritative protocol reference for anyone writing a new host.
- [`host_implementation_plan.md`](host_implementation_plan.md) — phased build plan with verification checkpoints and the risk matrix.
- [`host_implementation_guide.md`](host_implementation_guide.md) — long-form guide with sample code; read alongside the errata list in the plan.
- [`components/u8g2/README.md`](components/u8g2/README.md) — upstream u8g2 docs, in case the display driver is migrated.

"""
HearLink hardware smoke test.
Run against a powered ESP32 with the host joined to the HearLink WiFi AP.
"""
import socket
import struct
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from network.command_sender import CommandSender, CommandType, SoundCategory, BuzzerPattern

ESP32_IP = '192.168.4.1'
RX_PORT = 5005
TX_PORT = 5006
PACKET_SIZE = 1292
STRUCT_FORMAT = '<IIhBB' + ('i' * 320)

PASS = '\033[92mPASS\033[0m'
FAIL = '\033[91mFAIL\033[0m'


def step(label, ok):
    print(f"  [{PASS if ok else FAIL}] {label}")
    return ok


def confirm(prompt):
    ans = input(f"  [USER] {prompt} [y/n]: ").strip().lower()
    return ans == 'y'


def main():
    all_ok = True
    sender = CommandSender(ESP32_IP, TX_PORT)
    rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx_sock.bind(('', RX_PORT))
    rx_sock.settimeout(0.5)

    print("\n=== HearLink Smoke Test ===\n")

    # Step 1: Register with ESP32
    print("Step 1: Register host IP")
    sender.send_command(CommandType.CMD_TEST_MODE, 0, 0, 0)
    ok = step("CMD_TEST_MODE sent (no exception)", True)
    all_ok &= ok

    # Step 2: Packet reception
    print("\nStep 2: Packet reception (2 s)")
    packets = []
    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            data, _ = rx_sock.recvfrom(4096)
            packets.append(data)
        except socket.timeout:
            pass

    ok = step(f"Received {len(packets)} packets (≥300 expected)", len(packets) >= 300)
    all_ok &= ok

    # Step 3: Parse and validate packets
    print("\nStep 3: Packet parsing")
    if packets:
        valid = 0
        seq_list = []
        for data in packets[:50]:
            if len(data) != PACKET_SIZE:
                continue
            vals = struct.unpack(STRUCT_FORMAT, data)
            seq = vals[0]
            sub_seq = vals[3]
            audio_flat = vals[5:]
            if (all(-2**31 <= v < 2**31 for v in audio_flat[:10]) and sub_seq in (0, 1)):
                valid += 1
                if sub_seq == 0:
                    seq_list.append(seq)
        ok = step(f"Valid packets: {valid}/min(50,{len(packets)})", valid >= min(40, len(packets)))
        all_ok &= ok
        if len(seq_list) >= 2:
            monotonic = all(seq_list[i] <= seq_list[i + 1] for i in range(len(seq_list) - 1))
            ok = step("seq numbers monotonically non-decreasing", monotonic)
            all_ok &= ok

    # Step 4: Display icons at 4 compass directions
    print("\nStep 4: HUD compass icons (visual check)")
    for angle, label in [(0, 'front'), (90, 'right'), (180, 'back'), (270, 'left')]:
        sender.display_icon(angle, SoundCategory.DANGEROUS)
        print(f"  Sent icon at {angle}° ({label})")
        time.sleep(0.5)
    ok = confirm("Did the HUD display rotate icons at front / right / back / left?")
    all_ok &= step("HUD compass icon rotation (user confirmation)", ok)

    # Step 5: Fire all buzzers
    print("\nStep 5: Buzzer test (haptic check)")
    for angle, label in [(0, 'front'), (90, 'right'), (180, 'back'), (270, 'left')]:
        sender.fire_buzzer(angle, SoundCategory.DANGEROUS, BuzzerPattern.PATTERN_DOUBLE_TAP)
        print(f"  Fired buzzer at {angle}° ({label})")
        time.sleep(0.8)
    ok = confirm("Did all 4 buzzers fire in front / right / back / left order?")
    all_ok &= step("4-buzzer haptic sequence (user confirmation)", ok)

    # Step 6: Clear display
    print("\nStep 6: Clear display")
    sender.clear_display()
    ok = step("CMD_CLEAR_ALL sent (no exception)", True)
    all_ok &= ok

    rx_sock.close()
    sender.close()

    print()
    if all_ok:
        print("SMOKE TEST: PASS")
    else:
        print("SMOKE TEST: FAIL")
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())

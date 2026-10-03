import socket
import struct
import logging
from enum import IntEnum


class CommandType(IntEnum):
    CMD_DISPLAY_ICON = 0x01
    CMD_FIRE_BUZZER = 0x02
    CMD_CLEAR_ALL = 0x03
    CMD_CALIBRATE = 0x04
    CMD_SET_CALIBRATION = 0x05
    CMD_TEST_MODE = 0x10
    CMD_TEST_BUZZERS = 0x11
    CMD_TEST_DISPLAY = 0x12
    CMD_TEST_MICS = 0x13
    CMD_TEST_IMU = 0x14
    CMD_TEST_MICS_INDIV = 0x15
    CMD_TEST_BUZZER_SOLO = 0x16


class SoundCategory(IntEnum):
    DANGEROUS = 0
    SOCIAL = 1
    AMBIENT = 2


class BuzzerPattern(IntEnum):
    PATTERN_OFF = 0
    PATTERN_CONTINUOUS = 1
    PATTERN_PULSE_FAST = 2
    PATTERN_PULSE_SLOW = 3
    PATTERN_DOUBLE_TAP = 4


class IconType(IntEnum):
    ICON_DEFAULT = 0
    ICON_DANGER = 1
    ICON_SOCIAL = 2
    ICON_AMBIENT = 3


def _angle_to_direction_byte(angle_deg: float) -> int:
    return int((angle_deg % 360) * 256 / 360) & 0xFF


class CommandSender:
    STRUCT_FORMAT = 'BBBB'

    def __init__(self, esp32_ip: str = '192.168.4.1', port: int = 5006):
        self.esp32_addr = (esp32_ip, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.logger = logging.getLogger(__name__)

    def send_command(self, cmd_type: CommandType, direction: int = 0,
                     category: int = 0, pattern: int = 0):
        packet = struct.pack(self.STRUCT_FORMAT, int(cmd_type), direction, category, pattern)
        self.sock.sendto(packet, self.esp32_addr)
        self.logger.debug(f"Sent command: type=0x{int(cmd_type):02x} dir={direction} cat={category} pat={pattern}")

    def register_with_esp32(self):
        """Send a CMD_TEST_MODE packet so firmware learns our IP before streaming starts."""
        self.send_command(CommandType.CMD_TEST_MODE, 0, 0, 0)

    def display_icon(self, angle_deg: float, category: SoundCategory, icon_type: IconType = IconType.ICON_DEFAULT):
        direction_byte = _angle_to_direction_byte(angle_deg)
        self.send_command(CommandType.CMD_DISPLAY_ICON, direction_byte, int(category), int(icon_type))

    def fire_buzzer(self, angle_deg: float, category: SoundCategory,
                    pattern: BuzzerPattern = BuzzerPattern.PATTERN_CONTINUOUS):
        direction_byte = _angle_to_direction_byte(angle_deg)
        # Send category enum value (0/1/2) — firmware looks up intensity internally via category_to_intensity()
        self.send_command(CommandType.CMD_FIRE_BUZZER, direction_byte, int(category), int(pattern))

    def clear_display(self):
        self.send_command(CommandType.CMD_CLEAR_ALL)

    def trigger_calibration(self):
        self.send_command(CommandType.CMD_CALIBRATE)

    def set_calibration(self, channel: int, offset: int):
        self.send_command(CommandType.CMD_SET_CALIBRATION, channel, 0, offset & 0xFF)

    def close(self):
        self.sock.close()

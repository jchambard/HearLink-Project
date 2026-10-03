import struct
import pytest
from network.udp_receiver import UDPReceiver, AudioIMUSubPacket
from network.command_sender import _angle_to_direction_byte


STRUCT_FORMAT = '<IIhBB' + ('i' * 320)


def make_packet(seq=42, timestamp_us=1_000_000, imu_yaw_rate=1000,
                sub_seq=0, pad=0, audio_val=100):
    return struct.pack(STRUCT_FORMAT, seq, timestamp_us, imu_yaw_rate,
                       sub_seq, pad, *([audio_val] * 320))


class TestPacketParsing:
    def setup_method(self):
        self.receiver = UDPReceiver()

    def test_round_trip_basic(self):
        data = make_packet(seq=42, sub_seq=0)
        pkt = self.receiver._parse_packet(data)
        assert pkt.seq == 42
        assert pkt.sub_seq == 0
        assert pkt.timestamp_us == 1_000_000
        assert pkt.imu_yaw_rate == 1000
        assert len(pkt.audio) == 4
        assert len(pkt.audio[0]) == 80

    def test_round_trip_audio_values(self):
        data = make_packet(audio_val=0x00AABBCC)
        pkt = self.receiver._parse_packet(data)
        for ch in range(4):
            assert all(v == 0x00AABBCC for v in pkt.audio[ch])

    def test_round_trip_sub_seq_1(self):
        data = make_packet(seq=7, sub_seq=1)
        pkt = self.receiver._parse_packet(data)
        assert pkt.seq == 7
        assert pkt.sub_seq == 1

    def test_wrong_size_returns_none(self):
        result = self.receiver._parse_packet(b'\x00' * 100)
        assert result is None

    def test_empty_packet_returns_none(self):
        result = self.receiver._parse_packet(b'')
        assert result is None


class TestDirectionEncoding:
    def test_front(self):
        assert _angle_to_direction_byte(0) == 0

    def test_right(self):
        assert _angle_to_direction_byte(90) == 64

    def test_back(self):
        assert _angle_to_direction_byte(180) == 128

    def test_left(self):
        assert _angle_to_direction_byte(270) == 192

    def test_wrap_360(self):
        assert _angle_to_direction_byte(360) == 0

    def test_wrap_450(self):
        assert _angle_to_direction_byte(450) == _angle_to_direction_byte(90)

    def test_negative_angle(self):
        assert _angle_to_direction_byte(-90) == _angle_to_direction_byte(270)

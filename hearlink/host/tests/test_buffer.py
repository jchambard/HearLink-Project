import struct
import numpy as np
import pytest
from network.udp_receiver import AudioIMUSubPacket
from audio.buffer_manager import BufferManager


def make_subpacket(seq, sub_seq, imu_yaw_rate=131, audio_val=0):
    audio = [[audio_val] * 80 for _ in range(4)]
    return AudioIMUSubPacket(
        seq=seq,
        timestamp_us=seq * 10_000,
        imu_yaw_rate=imu_yaw_rate,
        sub_seq=sub_seq,
        pad=0,
        audio=audio,
    )


class TestBufferReassembly:
    def test_complete_buffer_shape(self):
        bm = BufferManager()
        result = bm.add_packet(make_subpacket(1, 0))
        assert result is None
        result = bm.add_packet(make_subpacket(1, 1))
        assert result is not None
        audio, yaw = result
        assert audio.shape == (4, 160)

    def test_yaw_conversion(self):
        bm = BufferManager()
        bm.add_packet(make_subpacket(1, 0, imu_yaw_rate=131))
        result = bm.add_packet(make_subpacket(1, 1, imu_yaw_rate=131))
        assert result is not None
        _, yaw = result
        assert abs(yaw - 1.0) < 1e-5

    def test_sub_seq_order_independent(self):
        bm = BufferManager()
        bm.add_packet(make_subpacket(5, 1))  # sub_seq=1 arrives first
        result = bm.add_packet(make_subpacket(5, 0))
        assert result is not None

    def test_audio_normalization(self):
        bm = BufferManager()
        val = int(128 * 2 ** 23)  # 128/256 = 0.5 after normalization
        bm.add_packet(make_subpacket(1, 0, audio_val=val))
        result = bm.add_packet(make_subpacket(1, 1, audio_val=val))
        audio, _ = result
        assert abs(float(audio[0, 0]) - 0.5) < 1e-3


class TestTTLEviction:
    def test_stale_entry_evicted(self):
        bm = BufferManager()
        # Inject sub_seq=0 for seq=1 (no sub_seq=1 follows)
        bm.add_packet(make_subpacket(1, 0))
        assert 1 in bm.pending_packets

        # Now receive a packet far ahead: seq=10, which should evict seq=1
        bm.add_packet(make_subpacket(10, 0))
        assert 1 not in bm.pending_packets

    def test_non_stale_not_evicted(self):
        bm = BufferManager()
        bm.add_packet(make_subpacket(5, 0))
        bm.add_packet(make_subpacket(8, 0))  # only 3 ahead, within TTL window of 5
        assert 5 in bm.pending_packets


class TestCircularBuffer:
    def test_get_recent_audio_shape(self):
        bm = BufferManager()
        # Write 2 seconds of data (200 complete buffers of 160 samples each)
        for seq in range(200):
            bm.add_packet(make_subpacket(seq, 0))
            bm.add_packet(make_subpacket(seq, 1))
        recent = bm.get_recent_audio(1.0)
        assert recent.shape == (4, 16000)

    def test_get_recent_audio_returns_latest(self):
        bm = BufferManager()
        # Fill with zeros then write known value near the end
        for seq in range(200):
            val = 1 if seq >= 190 else 0
            bm.add_packet(make_subpacket(seq, 0, audio_val=val))
            bm.add_packet(make_subpacket(seq, 1, audio_val=val))
        recent = bm.get_recent_audio(0.1)
        # Last 1600 samples — some should be non-zero (from seq 190-199 = 10 buffers = 1600 samples)
        assert np.any(recent != 0)

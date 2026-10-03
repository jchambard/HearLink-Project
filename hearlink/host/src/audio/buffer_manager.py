import numpy as np
import logging
from collections import defaultdict, deque
from typing import Optional, Tuple


class BufferManager:
    SAMPLES_PER_BUFFER = 160
    SAMPLES_PER_SUBPACKET = 80
    NUM_CHANNELS = 4
    SAMPLE_RATE = 16000
    BUFFER_DURATION_SEC = 2.0
    TTL_SEQ_WINDOW = 5  # evict incomplete buffers older than current_seq - TTL

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.pending_packets = defaultdict(dict)
        buffer_length = int(self.SAMPLE_RATE * self.BUFFER_DURATION_SEC)
        self.audio_buffer = np.zeros((self.NUM_CHANNELS, buffer_length), dtype=np.float32)
        self.buffer_write_pos = 0
        self.yaw_rate_buffer = deque(maxlen=200)
        self.last_seq = None
        self.dropped_packets = 0

    def add_packet(self, packet) -> Optional[Tuple[np.ndarray, float]]:
        seq = packet.seq
        sub_seq = packet.sub_seq

        # TTL eviction: drop incomplete buffers older than TTL_SEQ_WINDOW
        stale_keys = [k for k in list(self.pending_packets.keys()) if k < seq - self.TTL_SEQ_WINDOW]
        for k in stale_keys:
            del self.pending_packets[k]
            self.logger.debug(f"incomplete buffer dropped (seq={k})")

        if sub_seq == 0:
            if self.last_seq is not None and seq > self.last_seq + 1:
                lost = seq - self.last_seq - 1
                self.dropped_packets += lost
                self.logger.warning(f"Packet loss: {lost} buffers dropped (seq {self.last_seq} → {seq})")
            self.last_seq = seq

        self.pending_packets[seq][sub_seq] = packet

        if 0 in self.pending_packets[seq] and 1 in self.pending_packets[seq]:
            result = self._assemble_buffer(seq)
            del self.pending_packets[seq]
            return result

        return None

    def _assemble_buffer(self, seq: int) -> Tuple[np.ndarray, float]:
        p0 = self.pending_packets[seq][0]
        p1 = self.pending_packets[seq][1]

        audio_int32 = np.zeros((self.NUM_CHANNELS, self.SAMPLES_PER_BUFFER), dtype=np.int32)
        for ch in range(self.NUM_CHANNELS):
            audio_int32[ch, 0:80] = p0.audio[ch]
            audio_int32[ch, 80:160] = p1.audio[ch]

        audio_float = audio_int32.astype(np.float32) / (256.0 * 2 ** 23)

        yaw_rate_dps = p0.imu_yaw_rate / 131.0
        self.yaw_rate_buffer.append((p0.timestamp_us, yaw_rate_dps))

        # Write into circular buffer
        buf_len = self.audio_buffer.shape[1]
        pos = self.buffer_write_pos
        end = pos + self.SAMPLES_PER_BUFFER
        if end <= buf_len:
            self.audio_buffer[:, pos:end] = audio_float
        else:
            first = buf_len - pos
            self.audio_buffer[:, pos:] = audio_float[:, :first]
            self.audio_buffer[:, :end - buf_len] = audio_float[:, first:]
        self.buffer_write_pos = end % buf_len

        return audio_float, yaw_rate_dps

    def get_recent_audio(self, duration_sec: float) -> np.ndarray:
        n_samples = int(duration_sec * self.SAMPLE_RATE)
        buf_len = self.audio_buffer.shape[1]
        n_samples = min(n_samples, buf_len)
        pos = self.buffer_write_pos
        start = (pos - n_samples) % buf_len
        if start < pos:
            return self.audio_buffer[:, start:pos].copy()
        else:
            return np.concatenate([self.audio_buffer[:, start:], self.audio_buffer[:, :pos]], axis=1)

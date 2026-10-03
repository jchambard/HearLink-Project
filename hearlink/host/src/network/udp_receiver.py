import asyncio
import struct
import logging
from dataclasses import dataclass
from typing import Optional, Callable


@dataclass
class AudioIMUSubPacket:
    seq: int
    timestamp_us: int
    imu_yaw_rate: int
    sub_seq: int
    pad: int
    audio: list  # [4][80] int32 values


class UDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, packet_handler: Callable):
        self.packet_handler = packet_handler

    def datagram_received(self, data: bytes, addr: tuple):
        self.packet_handler(data, addr)

    def error_received(self, exc):
        logging.getLogger(__name__).warning(f"UDP error: {exc}")


class UDPReceiver:
    PACKET_SIZE = 1292
    STRUCT_FORMAT = '<IIhBB' + ('i' * 320)

    def __init__(self, port: int = 5005, callback: Optional[Callable] = None):
        self.port = port
        self.callback = callback
        self.logger = logging.getLogger(__name__)
        self._transport = None
        self._warn_count = 0

    async def start(self):
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: UDPProtocol(self._handle_packet),
            local_addr=('0.0.0.0', self.port)
        )
        self._transport = transport
        self.logger.info(f"UDP receiver listening on port {self.port}")
        return transport

    def stop(self):
        if self._transport:
            self._transport.close()

    def _handle_packet(self, data: bytes, addr: tuple):
        if len(data) != self.PACKET_SIZE:
            self._warn_count += 1
            if self._warn_count <= 3 or self._warn_count % 100 == 0:
                self.logger.warning(
                    f"Invalid packet size: {len(data)} (expected {self.PACKET_SIZE}) "
                    f"[occurrence #{self._warn_count}]"
                )
            return
        try:
            packet = self._parse_packet(data)
            if self.callback:
                self.callback(packet)
        except Exception as e:
            self.logger.error(f"Packet parsing error: {e}")

    def _parse_packet(self, data: bytes) -> Optional[AudioIMUSubPacket]:
        if len(data) != self.PACKET_SIZE:
            return None
        values = struct.unpack(self.STRUCT_FORMAT, data)
        seq = values[0]
        timestamp_us = values[1]
        imu_yaw_rate = values[2]
        sub_seq = values[3]
        pad = values[4]
        audio_flat = values[5:]
        audio = [list(audio_flat[i * 80:(i + 1) * 80]) for i in range(4)]
        return AudioIMUSubPacket(
            seq=seq,
            timestamp_us=timestamp_us,
            imu_yaw_rate=imu_yaw_rate,
            sub_seq=sub_seq,
            pad=pad,
            audio=audio,
        )

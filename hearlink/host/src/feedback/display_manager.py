import asyncio
import time
import logging
from dataclasses import dataclass
from typing import List
from feedback.event_router import SoundEvent, MAX_CONCURRENT_EVENTS, _CATEGORY_ICON
from network.command_sender import CommandSender

ICON_LIFETIME_SEC = 5.0
UPDATE_INTERVAL_SEC = 0.1  # re-send icons at 10 Hz while head is turning


@dataclass
class _ActiveIcon:
    collar_angle_deg: float
    event: SoundEvent
    expires_at: float


class DisplayManager:
    def __init__(self, command_sender: CommandSender):
        self.command_sender = command_sender
        self.logger = logging.getLogger(__name__)
        self._active: List[_ActiveIcon] = []

    def notify(self, events: List[SoundEvent]):
        """Register new detections. Replaces the active icon list (up to MAX_CONCURRENT_EVENTS)."""
        now = time.monotonic()
        for event in events[:MAX_CONCURRENT_EVENTS]:
            self._active.append(_ActiveIcon(
                collar_angle_deg=event.angle_collar_deg,
                event=event,
                expires_at=now + ICON_LIFETIME_SEC,
            ))
        # Keep only the newest MAX_CONCURRENT_EVENTS, sorted by category priority then confidence
        self._active = sorted(
            self._active,
            key=lambda a: (a.event.category.value, -a.event.confidence)
        )[:MAX_CONCURRENT_EVENTS]

    def update(self, current_yaw_deg: float):
        """Re-send all active icons with updated head-relative angles. Call this at ~10 Hz."""
        now = time.monotonic()
        self._active = [a for a in self._active if a.expires_at > now]

        for active in self._active:
            head_rel = (active.collar_angle_deg - current_yaw_deg + 90) % 360
            icon = _CATEGORY_ICON.get(active.event.category)
            self.command_sender.display_icon(head_rel, active.event.category, icon)

        if not self._active:
            self.command_sender.clear_display()

    async def update_loop(self, yaw_provider):
        """Background task: continuously update icon positions as head turns.
        yaw_provider is a callable returning current yaw in degrees."""
        while True:
            self.update(yaw_provider())
            await asyncio.sleep(UPDATE_INTERVAL_SEC)

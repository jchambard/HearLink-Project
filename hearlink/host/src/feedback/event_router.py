import logging
from dataclasses import dataclass
from typing import List
from classification.category_mapper import SoundCategory
from network.command_sender import CommandSender, BuzzerPattern, IconType

MAX_CONCURRENT_EVENTS = 3


@dataclass
class SoundEvent:
    angle_collar_deg: float    # for buzzer (collar-frame, no yaw subtraction)
    angle_head_rel_deg: float  # for HUD icon (head-relative)
    category: SoundCategory
    class_name: str
    confidence: float
    timestamp: float


_CATEGORY_PRIORITY = {
    SoundCategory.DANGEROUS: 0,
    SoundCategory.SOCIAL: 1,
    SoundCategory.AMBIENT: 2,
}

_CATEGORY_ICON = {
    SoundCategory.DANGEROUS: IconType.ICON_DANGER,
    SoundCategory.SOCIAL: IconType.ICON_SOCIAL,
    SoundCategory.AMBIENT: IconType.ICON_AMBIENT,
}


class EventRouter:
    def __init__(self, command_sender: CommandSender,
                 buzzer_prefs: dict | None = None):
        self.command_sender = command_sender
        self.logger = logging.getLogger(__name__)
        self.buzzer_prefs = buzzer_prefs or {
            SoundCategory.DANGEROUS: True,
            SoundCategory.SOCIAL: False,
            SoundCategory.AMBIENT: False,
        }

    def route_events(self, events: List[SoundEvent]):
        if not events:
            return

        # Sort by category priority first, then confidence descending
        sorted_events = sorted(
            events,
            key=lambda e: (_CATEGORY_PRIORITY[e.category], -e.confidence)
        )
        top_events = sorted_events[:MAX_CONCURRENT_EVENTS]

        for event in top_events:
            if self.buzzer_prefs.get(event.category, False):
                self.command_sender.fire_buzzer(
                    event.angle_collar_deg,
                    event.category,
                    BuzzerPattern.PATTERN_DOUBLE_TAP,
                )

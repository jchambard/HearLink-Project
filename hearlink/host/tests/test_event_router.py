import pytest
from unittest.mock import MagicMock, call
from classification.category_mapper import SoundCategory
from network.command_sender import BuzzerPattern, IconType
from feedback.event_router import EventRouter, SoundEvent, MAX_CONCURRENT_EVENTS


def make_event(category, confidence=0.8, collar_angle=0.0):
    return SoundEvent(
        angle_collar_deg=collar_angle,
        angle_head_rel_deg=collar_angle,
        category=category,
        class_name=category.name,
        confidence=confidence,
        timestamp=0.0,
    )


@pytest.fixture
def router_with_mock():
    sender = MagicMock()
    prefs = {
        SoundCategory.DANGEROUS: True,
        SoundCategory.SOCIAL: False,
        SoundCategory.AMBIENT: False,
    }
    router = EventRouter(sender, buzzer_prefs=prefs)
    return router, sender


class TestEventRouter:
    def test_display_icon_called_for_all_categories(self, router_with_mock):
        router, sender = router_with_mock
        events = [
            make_event(SoundCategory.DANGEROUS),
            make_event(SoundCategory.AMBIENT),
        ]
        router.route_events(events)
        assert sender.display_icon.call_count == 2

    def test_buzzer_only_for_dangerous(self, router_with_mock):
        router, sender = router_with_mock
        events = [
            make_event(SoundCategory.DANGEROUS),
            make_event(SoundCategory.AMBIENT),
        ]
        router.route_events(events)
        assert sender.fire_buzzer.call_count == 1
        args = sender.fire_buzzer.call_args[0]
        assert args[1] == SoundCategory.DANGEROUS

    def test_max_concurrent_events_respected(self, router_with_mock):
        router, sender = router_with_mock
        events = [make_event(SoundCategory.AMBIENT, confidence=0.6) for _ in range(5)]
        router.route_events(events)
        assert sender.display_icon.call_count == MAX_CONCURRENT_EVENTS

    def test_dangerous_routed_before_ambient(self, router_with_mock):
        router, sender = router_with_mock
        events = [
            make_event(SoundCategory.AMBIENT, confidence=0.9),
            make_event(SoundCategory.DANGEROUS, confidence=0.4),
        ]
        router.route_events(events)
        # First display_icon call should be for DANGEROUS (higher priority)
        first_call_args = sender.display_icon.call_args_list[0][0]
        assert first_call_args[1] == SoundCategory.DANGEROUS

    def test_empty_events_no_calls(self, router_with_mock):
        router, sender = router_with_mock
        router.route_events([])
        sender.display_icon.assert_not_called()
        sender.fire_buzzer.assert_not_called()

    def test_collar_angle_used_for_buzzer(self, router_with_mock):
        router, sender = router_with_mock
        event = SoundEvent(
            angle_collar_deg=90.0,
            angle_head_rel_deg=45.0,
            category=SoundCategory.DANGEROUS,
            class_name='Siren',
            confidence=0.9,
            timestamp=0.0,
        )
        router.route_events([event])
        buzzer_angle = sender.fire_buzzer.call_args[0][0]
        assert buzzer_angle == 90.0

    def test_head_rel_angle_used_for_display(self, router_with_mock):
        router, sender = router_with_mock
        event = SoundEvent(
            angle_collar_deg=90.0,
            angle_head_rel_deg=45.0,
            category=SoundCategory.DANGEROUS,
            class_name='Siren',
            confidence=0.9,
            timestamp=0.0,
        )
        router.route_events([event])
        display_angle = sender.display_icon.call_args[0][0]
        assert display_angle == 45.0

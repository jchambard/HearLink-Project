import asyncio
import logging
import time
from pathlib import Path
import yaml
import coloredlogs

from network.udp_receiver import UDPReceiver
from network.command_sender import CommandSender
from audio.buffer_manager import BufferManager
from audio.beamformer import DelayAndSumBeamformer
from classification.yamnet_classifier import YAMNetClassifier
from classification.category_mapper import CategoryMapper, SoundCategory
from imu.yaw_integrator import YawIntegrator
from feedback.event_router import EventRouter, SoundEvent
from feedback.display_manager import DisplayManager

CONFIG_DIR = Path(__file__).parent.parent / 'config'


class HearLinkHost:
    def __init__(self):
        coloredlogs.install(level='INFO', fmt='%(asctime)s %(name)s %(levelname)s %(message)s')
        self.logger = logging.getLogger('hearlink')

        with open(CONFIG_DIR / 'audio_config.yaml') as f:
            audio_cfg = yaml.safe_load(f)
        with open(CONFIG_DIR / 'network_config.yaml') as f:
            net_cfg = yaml.safe_load(f)

        self.logger.info("Loading YAMNet (~5 s cold start)...")
        self.yamnet = YAMNetClassifier()

        self.buffer_manager = BufferManager()
        self.beamformer = DelayAndSumBeamformer(
            radius_m=audio_cfg['mic_array']['radius_m'],
            num_beams=audio_cfg['beamforming']['num_beams'],
            speed_of_sound_mps=audio_cfg['beamforming']['speed_of_sound_mps'],
        )
        self.category_mapper = CategoryMapper(str(CONFIG_DIR / 'yamnet_categories.yaml'))
        self.yaw_integrator = YawIntegrator()

        buzzer_prefs_raw = audio_cfg.get('buzzer_preferences', {})
        buzzer_prefs = {
            SoundCategory.DANGEROUS: buzzer_prefs_raw.get('dangerous', True),
            SoundCategory.SOCIAL: buzzer_prefs_raw.get('social', False),
            SoundCategory.AMBIENT: buzzer_prefs_raw.get('ambient', False),
        }

        self.command_sender = CommandSender(net_cfg['esp32_ip'], net_cfg['tx_port'])
        self.event_router = EventRouter(self.command_sender, buzzer_prefs)
        self.display_manager = DisplayManager(self.command_sender)

        self.receiver = UDPReceiver(port=net_cfg['rx_port'], callback=self._handle_packet)

        self.process_interval = audio_cfg['processing']['process_interval_sec']
        self.window_duration = audio_cfg['processing']['window_duration_sec']
        self._last_process_time = 0.0

    def _handle_packet(self, packet):
        self.buffer_manager.add_packet(packet)
        if packet.sub_seq == 0:
            self.yaw_integrator.add_sample(packet.imu_yaw_rate, packet.timestamp_us)

    async def _wait_for_calibration(self):
        self.logger.info("IMU calibrating — hold still for ~2 seconds...")
        last_log = time.time()
        while not self.yaw_integrator.is_calibrated():
            pct = int(self.yaw_integrator.progress() * 100)
            samples = int(self.yaw_integrator.progress() * 200)
            now = time.time()
            if now - last_log >= 1.0:
                self.logger.info(f"IMU calibrating: {pct}% ({samples}/200 samples)")
                last_log = now
            await asyncio.sleep(0.1)
        self.logger.info("IMU calibrated. Ready.")

    async def _processing_loop(self):
        while True:
            now = asyncio.get_running_loop().time()
            if now - self._last_process_time >= self.process_interval:
                self._last_process_time = now
                audio = self.buffer_manager.get_recent_audio(self.window_duration)
                if audio.shape[1] < 160:
                    await asyncio.sleep(0.05)
                    continue

                detections = self.beamformer.detect_directions(audio, top_k=3)
                self.logger.debug(f"Beamformer: {len(detections)} direction(s) detected")
                current_yaw = self.yaw_integrator.get_yaw()
                events = []
                for angle_c, energy, beam_audio in detections:
                    results = self.yamnet.classify(beam_audio, top_k=5)
                    self.logger.debug(f"  YAMNet top: {results[0][0]} ({results[0][1]:.2f}) at {angle_c:.0f}°")
                    categorized = self.category_mapper.map_predictions(results)
                    if not categorized:
                        self.logger.debug(f"  No category match above threshold at {angle_c:.0f}°")
                        continue
                    category, confidence, class_name = categorized[0]
                    events.append(SoundEvent(
                        angle_collar_deg=angle_c,
                        angle_head_rel_deg=(angle_c - current_yaw) % 360,
                        category=category,
                        class_name=class_name,
                        confidence=confidence,
                        timestamp=now,
                    ))
                    self.logger.info(f"Sound: {class_name} ({category.name}) at {angle_c:.0f}° "
                                     f"(head-rel {(angle_c - current_yaw) % 360:.0f}°) conf={confidence:.2f}")

                if events:
                    self.event_router.route_events(events)   # fires buzzers
                    self.display_manager.notify(events)      # registers icons for tracking

            await asyncio.sleep(0.01)

    async def run(self):
        transport = await self.receiver.start()
        self.logger.info("Registering host IP with ESP32...")
        self.command_sender.register_with_esp32()

        self.logger.info("Starting processing loop.")
        try:
            await asyncio.gather(
                self._processing_loop(),
                self.display_manager.update_loop(lambda: 0.0),
            )
        except asyncio.CancelledError:
            pass
        finally:
            self.logger.info("Shutting down...")
            self.command_sender.clear_display()
            self.command_sender.close()
            transport.close()


async def _main():
    app = HearLinkHost()
    await app.run()


if __name__ == '__main__':
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass

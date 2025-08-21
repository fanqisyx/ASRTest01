"""
TTS App (independent)
- Subscribes to MQTT tts/speak and/or consumes SQLite tts tasks.
- Speaks via pyttsx3.
"""
import os
import json
import time

from shared.db import init_db, claim_next_task, finish_task
from shared.mqtt_bus import (
    MqttConfig, create_client, publish_json, subscribe,
    TOPIC_TTS_SPEAK, TOPIC_TTS_CTRL
)
from tts_module import speak_text_safe, stop_tts
from shared.config_helper import read_config


class TtsWorker:
    def __init__(self):
        conf = read_config()
        self.enable_mqtt = bool(conf.get('enable_mqtt', True))
        self.enable_sqlite = bool(conf.get('enable_sqlite', True))
        if self.enable_sqlite:
            init_db()
        self.client = create_client(MqttConfig(), self.on_message) if self.enable_mqtt else None
        if self.client:
            subscribe(self.client, TOPIC_TTS_SPEAK)
            subscribe(self.client, TOPIC_TTS_CTRL)
            self.client.loop_start()
        self.stop_flag = False

    def on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode('utf-8'))
            if msg.topic == TOPIC_TTS_SPEAK:
                if self.enable_sqlite:
                    from shared.db import create_task
                    create_task('tts', json.dumps({'text': data.get('text',''), 'ref_id': data.get('ref_id')}))
            elif msg.topic == TOPIC_TTS_CTRL:
                action = data.get('action')
                if action == 'stop':
                    stop_tts()
        except Exception:
            pass

    def loop(self):
        while not self.stop_flag:
            claimed = claim_next_task('tts') if self.enable_sqlite else None
            if not claimed:
                time.sleep(0.1)
                continue
            task_id, payload = claimed
            try:
                body = json.loads(payload)
                text = body.get('text', '')
                if text:
                    speak_text_safe(text)
                if self.enable_sqlite:
                    finish_task(task_id, json.dumps({'ok': True}, ensure_ascii=False), 'done')
            except Exception as e:
                if self.enable_sqlite:
                    finish_task(task_id, json.dumps({'ok': False, 'err': str(e)}, ensure_ascii=False), 'error')


def main():
    worker = TtsWorker()
    print('[TTS] app started. Press Ctrl+C to stop.')
    try:
        worker.loop()
    except KeyboardInterrupt:
        pass
    finally:
        if worker.client:
            worker.client.loop_stop()
            worker.client.disconnect()


if __name__ == '__main__':
    main()

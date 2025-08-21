"""
ASR Service
- Captures one utterance via Vosk and publishes to MQTT and SQLite.
- Minimal loop: recognize -> insert message -> publish -> sleep short.
"""
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))  # add project root for 'shared' imports
import json
import time
import threading
from typing import Optional

from shared.db import init_db, insert_message, create_task
from shared.config_helper import read_config
from shared.mqtt_bus import (
    MqttConfig, create_client, publish_json, TOPIC_ASR_TEXT, TOPIC_LLM_ASK
)
from vosk_module import recognize_speech


def main():
    conf = read_config()
    enable_mqtt = bool(conf.get('enable_mqtt', True))
    enable_sqlite = bool(conf.get('enable_sqlite', True))

    if enable_sqlite:
        init_db()
    mqtt_client = create_client(MqttConfig(), None) if enable_mqtt else None
    if mqtt_client:
        mqtt_client.loop_start()

    stop_event = threading.Event()
    discard_event = threading.Event()
    model_path = conf.get('vosk_model_path')

    print('[ASR] service started. Press Ctrl+C to stop.')
    try:
        while True:
            text = recognize_speech(model_path=model_path, stop_event=stop_event, discard_event=discard_event)
            text = (text or '').strip()
            if not text:
                continue
            msg_id = None
            if enable_sqlite:
                msg_id = insert_message('user', text)
                # also create an LLM task in DB for decoupled processing
                create_task('llm', json.dumps({"text": text, "ref_id": msg_id}), ref_id=msg_id)
            if enable_mqtt:
                publish_json(mqtt_client, TOPIC_ASR_TEXT, {"text": text, "ref_id": msg_id})
                publish_json(mqtt_client, TOPIC_LLM_ASK, {"text": text, "ref_id": msg_id})
            print(f'[ASR] text -> {text}')
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        if mqtt_client:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()


if __name__ == '__main__':
    main()

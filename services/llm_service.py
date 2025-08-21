"""
LLM Service
- Subscribes to MQTT llm/ask and consumes SQLite llm tasks.
- Queries LMStudio and publishes llm/answer and a tts task.
"""
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
import json
import threading
import time

from shared.db import init_db, claim_next_task, finish_task, insert_message, create_task
from shared.mqtt_bus import (
    MqttConfig, create_client, publish_json, subscribe,
    TOPIC_LLM_ASK, TOPIC_LLM_ANSWER, TOPIC_TTS_SPEAK
)
from lmstudio_module import query_lmstudio
from shared.config_helper import read_config


class LlmWorker:
    def __init__(self):
        # load config first
        self.conf = read_config()
        self.enable_mqtt = bool(self.conf.get('enable_mqtt', True))
        self.enable_sqlite = bool(self.conf.get('enable_sqlite', True))
        if self.enable_sqlite:
            init_db()
        self.client = create_client(MqttConfig(), self.on_message) if self.enable_mqtt else None
        if self.client:
            subscribe(self.client, TOPIC_LLM_ASK)
            self.client.loop_start()
        self.stop = False
        self.lm_url = self.conf.get('lmstudio_url', 'http://localhost:1234/v1/chat/completions')
        self.lm_model = self.conf.get('lmstudio_model', 'your-model-name')
        self.no_think = bool(self.conf.get('no_think', False))

    def on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode('utf-8'))
            text = data.get('text')
            ref_id = data.get('ref_id')
            if text and self.enable_sqlite:
                create_task('llm', json.dumps({'text': text, 'ref_id': ref_id}), ref_id=ref_id)
        except Exception:
            pass

    def loop(self):
        while not self.stop:
            claimed = claim_next_task('llm') if self.enable_sqlite else None
            if not claimed:
                time.sleep(0.1)
                continue
            task_id, payload = claimed
            try:
                body = json.loads(payload)
                text = body.get('text', '')
                ref_id = body.get('ref_id')
                send = text + ' /no_think' if self.no_think else text
                thinking, answer = query_lmstudio(send, self.lm_url, self.lm_model)
                if self.enable_sqlite:
                    insert_message('assistant', answer or '', json.dumps({'thinking': thinking or ''}, ensure_ascii=False))
                    # enqueue tts
                    create_task('tts', json.dumps({'text': answer or '', 'ref_id': ref_id}))
                    finish_task(task_id, json.dumps({'ok': True}, ensure_ascii=False), 'done')
                if self.enable_mqtt:
                    publish_json(self.client, TOPIC_LLM_ANSWER, {'thinking': thinking, 'answer': answer, 'ref_id': ref_id})
                    publish_json(self.client, TOPIC_TTS_SPEAK, {'text': answer or '', 'ref_id': ref_id})
            except Exception as e:
                if self.enable_sqlite:
                    finish_task(task_id, json.dumps({'ok': False, 'err': str(e)}, ensure_ascii=False), 'error')


def main():
    worker = LlmWorker()
    print('[LLM] service started. Press Ctrl+C to stop.')
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

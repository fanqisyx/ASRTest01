"""
TTS App (independent)
- 输入来源：
    1) 轮询 LLM 自有数据库 events 第一行（覆盖写）并在 time 变化时播报；
    2) 兼容旧 SQLite 任务队列（shared.db.tasks kind='tts'），可开关；
    3) MQTT 订阅 tts/speak 和 tts/control（stop）。
- 语音合成：pyttsx3。
"""
import os
import json
import time
import sqlite3

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
        # LLM DB 路径（可为空）；存在则优先轮询
        self.llm_db_path = self._normalize_path(conf.get('llm_db_path'))
        self._last_llm_time = None
        # 轮询周期
        self.poll_interval = float(conf.get('tts_poll_interval', conf.get('asr_poll_interval', 0.5)))
        if self.enable_sqlite:
            init_db()
        self.client = create_client(MqttConfig(), self.on_message) if self.enable_mqtt else None
        if self.client:
            subscribe(self.client, TOPIC_TTS_SPEAK)
            subscribe(self.client, TOPIC_TTS_CTRL)
            self.client.loop_start()
        self.stop_flag = False
        # 当未启用旧任务队列时，MQTT 的 speak 将进入此内存队列
        self._mqtt_direct_queue = []

    def _normalize_path(self, p):
        if not p:
            return None
        try:
            s = str(p).strip().strip('"').strip("'").strip('“”').strip('‘’')
            if not os.path.isabs(s):
                base = os.path.dirname(os.path.abspath(__file__))
                s = os.path.abspath(os.path.join(base, s))
            return s
        except Exception:
            return p

    def on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode('utf-8'))
            if msg.topic == TOPIC_TTS_SPEAK:
                text = data.get('text','')
                ref_id = data.get('ref_id')
                if self.enable_sqlite:
                    from shared.db import create_task
                    create_task('tts', json.dumps({'text': text, 'ref_id': ref_id}))
                else:
                    if text:
                        self._mqtt_direct_queue.append(text)
            elif msg.topic == TOPIC_TTS_CTRL:
                action = data.get('action')
                if action == 'stop':
                    stop_tts()
        except Exception:
            pass

    def _read_llm_first_event(self):
        """读取 LLM DB 的第一行事件，返回 (time_str, command, parameter) 或 None。"""
        if not self.llm_db_path or not os.path.exists(self.llm_db_path):
            return None
        try:
            conn = sqlite3.connect(self.llm_db_path)
            try:
                cur = conn.cursor()
                cur.execute("SELECT time, command, parameter FROM events ORDER BY id LIMIT 1")
                row = cur.fetchone()
                if not row:
                    return None
                return row[0], row[1], row[2]
            finally:
                conn.close()
        except Exception:
            return None

    def loop(self):
        while not self.stop_flag:
            did_work = False

            # 1) 轮询 LLM DB 事件（若配置了路径）
            evt = self._read_llm_first_event()
            if evt:
                llm_time, command, parameter = evt
                if llm_time and llm_time != self._last_llm_time:
                    self._last_llm_time = llm_time
                    try:
                        text_to_speak = None
                        try:
                            pobj = json.loads(parameter)
                            if isinstance(pobj, dict):
                                val = pobj.get('play')
                                if isinstance(val, (dict, list)):
                                    val = json.dumps(val, ensure_ascii=False)
                                elif val is not None:
                                    val = str(val)
                                text_to_speak = val
                        except Exception:
                            # 不回退到原文或其他字段，仅在存在 play 时播报
                            pass
                        if isinstance(text_to_speak, str) and text_to_speak.strip():
                            speak_text_safe(text_to_speak)
                            did_work = True
                    except Exception:
                        pass

            # 2) 兼容：旧 SQLite 任务队列
            if not did_work and self.enable_sqlite:
                claimed = claim_next_task('tts')
                if claimed:
                    task_id, payload = claimed
                    try:
                        body = json.loads(payload)
                        text = body.get('text', '')
                        if text:
                            speak_text_safe(text)
                        finish_task(task_id, json.dumps({'ok': True}, ensure_ascii=False), 'done')
                        did_work = True
                    except Exception as e:
                        finish_task(task_id, json.dumps({'ok': False, 'err': str(e)}, ensure_ascii=False), 'error')

            # 3) MQTT 直接队列
            if not did_work and self._mqtt_direct_queue:
                try:
                    text = self._mqtt_direct_queue.pop(0)
                except Exception:
                    text = None
                if text:
                    try:
                        speak_text_safe(text)
                        did_work = True
                    except Exception:
                        pass

            if not did_work:
                time.sleep(self.poll_interval)


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

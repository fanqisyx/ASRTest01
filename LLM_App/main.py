"""
LLM App (independent)
- 新需求：
  1) 三个可配置路径：系统提示词TXT、ASR数据库(只读)、LLM自有数据库(只写)。
  2) 周期轮询ASR数据库 events 表：读取 time，若变化则取 parameter(JSON)，将其中 listened 字段作为用户输入；
      每次发送前，读取系统提示词TXT并放入 system role。
  3) LLM 自有数据库 events 表采用“覆盖第一行”策略：软件打开时清空；写入字段(id, time, command, parameter)。
      - id 为应用内自增计数，启动清零；每次收到模型回复后加1并写入第一行。
      - time 为当前时间(YYYY-MM-DD HH:MM:SS)。
      - 当模型回复是JSON字符串：command=JSON.command，parameter=JSON.parameter；否则 command='play'，parameter=原文。
"""
import os
import json
import threading
import time
from datetime import datetime

from shared.db import init_db as init_legacy_db, claim_next_task, finish_task, insert_message, create_task
from shared.mqtt_bus import (
    MqttConfig, create_client, publish_json, subscribe,
    TOPIC_LLM_ASK, TOPIC_LLM_ANSWER, TOPIC_TTS_SPEAK
)
from lmstudio_module import query_lmstudio
from shared.config_helper import read_config
from shared.asr_reader import read_latest_event as asr_read_latest
from shared.llm_db import init_llm_db, clear_llm_events, overwrite_llm_first_event


class LlmWorker:
    def __init__(self):
        self.conf = read_config()
        # 轮询周期(s)
        self.poll_interval = float(self.conf.get('asr_poll_interval', 0.5))
        # 路径配置（允许外部配置独立路径；若未设置则兼容旧字段 db_path）
        self.system_prompt_path = self._normalize_path(self.conf.get('system_prompt_path'))
        # MQTT/旧SQLite任务开关（保留兼容，但ASR轮询和LLM自有DB是新主路径）
        self.enable_mqtt = bool(self.conf.get('enable_mqtt', True))
        self.enable_sqlite = bool(self.conf.get('enable_sqlite', True))
        if self.enable_sqlite:
            init_legacy_db()
        # 初始化 LLM 自有数据库，并在启动时清空
        init_llm_db()
        clear_llm_events()
        # 本地自增 id，从0开始
        self.local_id = 0
        self.client = create_client(MqttConfig(), self.on_message) if self.enable_mqtt else None
        if self.client:
            subscribe(self.client, TOPIC_LLM_ASK)
            self.client.loop_start()
        self.stop = False
        self.lm_url = self.conf.get('lmstudio_url', 'http://localhost:1234/v1/chat/completions')
        self.lm_model = self.conf.get('lmstudio_model', 'your-model-name')
        self.no_think = bool(self.conf.get('no_think', False))
        # 记录上次看到的 ASR time 值
        self._last_asr_time = None
        # GUI 事件回调（可由外部设置）：on_event(event_name: str, data: dict)
        self.on_event = None

    def _emit(self, event: str, data: dict):
        try:
            if callable(self.on_event):
                self.on_event(event, data)
        except Exception:
            pass

    def _normalize_path(self, p: str | None) -> str | None:
        if not p:
            return None
        try:
            p = p.strip().strip('"').strip("'").strip('“”').strip('‘’')
            if not os.path.isabs(p):
                base = os.path.dirname(os.path.abspath(__file__))
                p = os.path.abspath(os.path.join(base, p))
            return p
        except Exception:
            return p

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
            # 1) 轮询 ASR DB 的最新事件
            try:
                latest = asr_read_latest()
                if latest:
                    asr_time, param_str = latest
                    if asr_time:
                        if self._last_asr_time is None:
                            # 首次读取仅建立基线，不触发发送
                            self._last_asr_time = asr_time
                        elif asr_time != self._last_asr_time:
                            self._last_asr_time = asr_time
                            user_text = self._extract_listened(param_str)
                            if user_text:
                                self._handle_user_text(user_text)
            except Exception:
                pass

            # 2) 兼容：若需要，也可继续处理旧 SQLite 任务队列
            claimed = claim_next_task('llm') if self.enable_sqlite else None
            if claimed:
                task_id, payload = claimed
                try:
                    body = json.loads(payload)
                    text = body.get('text', '')
                    ref_id = body.get('ref_id')
                    self._handle_user_text(text, ref_id)
                    finish_task(task_id, json.dumps({'ok': True}, ensure_ascii=False), 'done')
                except Exception as e:
                    finish_task(task_id, json.dumps({'ok': False, 'err': str(e)}, ensure_ascii=False), 'error')

            time.sleep(self.poll_interval)

    def _read_system_prompt(self) -> str:
        # 每次调用都从文件读取一次
        try:
            path = self.system_prompt_path
            if path and os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read().strip()
        except Exception:
            pass
        # 兜底：沿用 lmstudio_module 内置的 SYSTEM_PROMPT
        from lmstudio_module import SYSTEM_PROMPT
        return SYSTEM_PROMPT

    def _extract_listened(self, parameter_str: str) -> str | None:
        try:
            obj = json.loads(parameter_str)
            val = obj.get('listened')
            if isinstance(val, str) and val.strip():
                return val.strip()
        except Exception:
            return None
        return None

    def _handle_user_text(self, text: str, ref_id=None):
        # 拼接 system prompt 与用户输入
        sp = self._read_system_prompt()
        send = text + (' /no_think' if self.no_think else '')
        # 通知 GUI：最新 listened
        self._emit('listened', {'text': text})
        # 调用 LLM
        thinking, answer = query_lmstudio(send, self.lm_url, self.lm_model, system_prompt=sp)
        # 解析回复：JSON or 非JSON
        cmd, param = self._parse_reply(answer)
        # 自增 id、时间戳
        self.local_id += 1 if self.local_id >= 0 else 1
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # 覆盖写入 LLM 自有 DB 第一行
        payload_json = param if isinstance(param, str) else json.dumps(param, ensure_ascii=False)
        overwrite_llm_first_event(self.local_id, now, cmd, payload_json)
        # 通知 GUI：回复内容
        self._emit('replied', {'command': cmd, 'parameter': payload_json})
        # 兼容性：原消息表、TTS任务、MQTT 通知
        if self.enable_sqlite:
            insert_message('assistant', answer or '', json.dumps({'thinking': thinking or '', 'system': sp}, ensure_ascii=False))
            create_task('tts', json.dumps({'text': answer or '', 'ref_id': ref_id}))
        if self.enable_mqtt and self.client:
            publish_json(self.client, TOPIC_LLM_ANSWER, {'thinking': thinking, 'answer': answer, 'ref_id': ref_id})
            publish_json(self.client, TOPIC_TTS_SPEAK, {'text': answer or '', 'ref_id': ref_id})

    def _parse_reply(self, answer: str) -> tuple[str, str | dict]:
        # JSON -> 提取 command/parameter；否则 command='play', parameter=全文
        try:
            obj = json.loads(answer)
            cmd = obj.get('command', 'play')
            param = obj.get('parameter', obj)
            # parameter 若非字符串，后续会 json.dumps
            return cmd, param
        except Exception:
            # 非 JSON：返回 command='play'，并将 parameter 改为包含 command 与 play 的 JSON 字符串
            safe_text = answer or ''
            param_obj = {"command": "play", "play": safe_text}
            return 'play', json.dumps(param_obj, ensure_ascii=False)


def main():
    worker = LlmWorker()
    print('[LLM] app started. Press Ctrl+C to stop.')
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

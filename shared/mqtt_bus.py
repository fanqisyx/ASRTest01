import json
import os
from dataclasses import dataclass
from typing import Callable, Optional, Any

try:
    import paho.mqtt.client as mqtt  # type: ignore
except Exception:
    mqtt = None  # graceful fallback when paho-mqtt is not installed
import uuid

DEFAULT_BROKER = os.environ.get('MQTT_BROKER', 'localhost')
DEFAULT_PORT = int(os.environ.get('MQTT_PORT', '1883'))

TOPIC_ASR_TEXT = 'asr/text'            # payload: {"text": "...", "ref_id": optional}
TOPIC_LLM_ASK = 'llm/ask'              # payload: {"text": "...", "ref_id": optional}
TOPIC_LLM_ANSWER = 'llm/answer'        # payload: {"thinking": "...", "answer": "...", "ref_id": optional}
TOPIC_TTS_SPEAK = 'tts/speak'          # payload: {"text": "...", "priority": false, "ref_id": optional}
TOPIC_TTS_CTRL = 'tts/control'         # payload: {"action": "stop|pause|resume"}


@dataclass
class MqttConfig:
    host: str = DEFAULT_BROKER
    port: int = DEFAULT_PORT
    client_id: Optional[str] = None


def create_client(conf: MqttConfig, on_message: Optional[Callable] = None) -> Any:
    """Create and connect an MQTT client. Returns None if paho-mqtt is unavailable."""
    if mqtt is None:
        return None
    cid = conf.client_id or f"asrbus-{uuid.uuid4().hex[:8]}"
    client = mqtt.Client(client_id=cid)
    if on_message:
        client.on_message = on_message
    try:
        client.connect(conf.host, conf.port, 60)
    except Exception as e:
        # 连接失败，优雅降级：返回 None，使上层仅使用 SQLite
        try:
            print(f"[MQTT] 连接 {conf.host}:{conf.port} 失败，已禁用MQTT。原因: {e}")
        except Exception:
            pass
        return None
    return client


def publish_json(client: Any, topic: str, data: dict):
    if client is None:
        return
    payload = json.dumps(data, ensure_ascii=False)
    try:
        client.publish(topic, payload)
    except Exception:
        pass


def subscribe(client: Any, topic: str):
    if client is None:
        return
    try:
        client.subscribe(topic)
    except Exception:
        pass


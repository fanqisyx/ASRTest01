import json
import os
from dataclasses import dataclass
from typing import Callable, Optional, Any

try:
    import paho.mqtt.client as mqtt  # type: ignore
except Exception:
    mqtt = None
import uuid

DEFAULT_BROKER = os.environ.get('MQTT_BROKER', 'localhost')
DEFAULT_PORT = int(os.environ.get('MQTT_PORT', '1883'))

TOPIC_ASR_TEXT = 'asr/text'
TOPIC_LLM_ASK = 'llm/ask'
TOPIC_LLM_ANSWER = 'llm/answer'
TOPIC_TTS_SPEAK = 'tts/speak'
TOPIC_TTS_CTRL = 'tts/control'


@dataclass
class MqttConfig:
    host: str = DEFAULT_BROKER
    port: int = DEFAULT_PORT
    client_id: Optional[str] = None


def create_client(conf: MqttConfig, on_message: Optional[Callable] = None) -> Any:
    if mqtt is None:
        return None
    cid = conf.client_id or f"asrbus-{uuid.uuid4().hex[:8]}"
    client = mqtt.Client(client_id=cid)
    if on_message:
        client.on_message = on_message
    try:
        client.connect(conf.host, conf.port, 60)
    except Exception as e:
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

"""
ASR App (independent)
- Captures one utterance via Vosk and publishes to MQTT and/or SQLite per config.
"""
import os
import json
import time
import threading
import winsound

from shared.db import init_db, insert_event, overwrite_first_event, clear_events
from shared.config_helper import read_config
from shared.mqtt_bus import (
    MqttConfig, create_client, publish_json, TOPIC_ASR_TEXT, TOPIC_LLM_ASK, TOPIC_TTS_SPEAK
)
from vosk_module import recognize_speech


# ---- 拼音模糊匹配工具 ----
def _safe_import_pypinyin():
    try:
        from pypinyin import lazy_pinyin  # type: ignore
        return lazy_pinyin
    except Exception:
        return None


def _to_pinyin_normalized(text: str, fuzzy_hf: bool = False) -> str:
    """将中文文本转为无声调拼音并做简单模糊归一，便于宽松匹配。
    规则：
    - zh->z, ch->c, sh->s
    - ang->an, eng->en, ing->in（去尾 g）
    - ü 统一为 u
    - 可选：h/f 归一（把 f 映射为 h），用于特定口音容错
    非中文则保留字母数字，其他符号去除。
    """
    if not text:
        return ''
    lazy_pinyin = _safe_import_pypinyin()
    if lazy_pinyin is None:
        # 无 pypinyin 时的降级：仅保留字母数字并小写
        base = ''.join(ch for ch in text.lower() if ch.isalnum())
    else:
        # 将中文序列转为拼音，非中文会原样保留为字符，再统一过滤
        py_list = lazy_pinyin(text, errors='default')
        base = ''.join(py_list).lower()

    # 常见归一
    base = (
        base.replace('zh', 'z')
            .replace('ch', 'c')
            .replace('sh', 's')
            .replace('ang', 'an')
            .replace('eng', 'en')
            .replace('ing', 'in')
            .replace('ü', 'u')
            .replace('v', 'u')
    )
    if fuzzy_hf:
        base = base.replace('f', 'h')

    # 仅保留字母数字
    base = ''.join(ch for ch in base if ch.isalnum())
    return base


def _match_wakeword(text: str, wake: str, fuzzy_hf: bool = False) -> bool:
    """宽松匹配：原文包含 或 拼音归一后包含。"""
    if not text or not wake:
        return False
    if wake in text:
        return True
    p_text = _to_pinyin_normalized(text, fuzzy_hf=fuzzy_hf)
    p_wake = _to_pinyin_normalized(wake, fuzzy_hf=fuzzy_hf)
    return bool(p_wake) and (p_wake in p_text)


def listen_loop(stop_event: threading.Event, on_event=None):
    conf = read_config()
    enable_mqtt = bool(conf.get('enable_mqtt', True))
    enable_sqlite = bool(conf.get('enable_sqlite', True))
    enable_wakeword = bool(conf.get('enable_wakeword', False))
    wakeword = (conf.get('wakeword') or '').strip()
    wake_beep_path = (conf.get('wake_beep_path') or '').strip()
    # 去除可能包裹路径的引号（中英文）
    if wake_beep_path:
        for ql, qr in [("\"", "\""), ("'", "'"), ('“', '”'), ('"', '"')]:
            if wake_beep_path.startswith(ql) and wake_beep_path.endswith(qr) and len(wake_beep_path) >= 2:
                wake_beep_path = wake_beep_path[1:-1].strip()
                break
    # 语音屏蔽收听控制
    mic_guard_file = conf.get('mic_guard_file', 'mic_guard.txt')  # 内容为'1'时可收音
    mic_guard_interval = float(conf.get('mic_guard_interval', 0.5))  # 轮询间隔秒

    if enable_sqlite:
        init_db()
        # 启动时清空（仅留空，不保留历史）
        try:
            clear_events()
        except Exception:
            pass
    mqtt_client = create_client(MqttConfig(), None) if enable_mqtt else None
    if mqtt_client:
        mqtt_client.loop_start()

    discard_event = threading.Event()
    model_path = conf.get('vosk_model_path')
    awake = False  # 唤醒状态：False 等待唤醒；True 已唤醒，下一句视为指令
    # 拼音模糊参数（可在 config.json 中配置 pinyin_fuzzy_hf: true/false）
    pinyin_fuzzy_hf = bool(conf.get('pinyin_fuzzy_hf', False))

    print('[ASR] app started. Press Ctrl+C to stop.')
    event_id = 0  # 本地自增事件ID（保留但当前逻辑不再依赖递增）
    try:
        while not stop_event.is_set():
            # 语音屏蔽文件轮询
            try:
                with open(mic_guard_file, 'r', encoding='utf-8') as f:
                    can_listen = f.read().strip() == '1'
            except Exception:
                can_listen = False
            if not can_listen:
                time.sleep(mic_guard_interval)
                continue

            text = recognize_speech(model_path=model_path, stop_event=stop_event, discard_event=discard_event)
            text = (text or '').strip()
            if not text:
                continue
            # 唤醒词逻辑
            if enable_wakeword:
                if not awake:
                    # 未唤醒阶段：总是把听到的内容通过回调给 GUI 展示
                    try:
                        if on_event:
                            on_event('heard', {"text": text})
                    except Exception:
                        pass
                    # 匹配到唤醒词后进入唤醒态；唤醒前不写 DB
                    if wakeword and _match_wakeword(text, wakeword, fuzzy_hf=pinyin_fuzzy_hf):
                        awake = True
                        # 立即提示 UI 已唤醒
                        try:
                            if on_event:
                                on_event('wake', {})
                        except Exception:
                            pass
                        # 播放本地提示音（异步，不阻塞识别主循环）
                        try:
                            if wake_beep_path and os.path.exists(wake_beep_path):
                                winsound.PlaySound(wake_beep_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                        except Exception:
                            pass
                        print(f'[ASR] wake -> {text}')
                    # 本轮不作为指令转发，也不写DB
                    time.sleep(0.1)
                    continue
                else:
                    # 已唤醒：本轮识别作为用户“命令”
                    msg_id = None
                    if enable_sqlite:
                        now = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                        # 覆盖数据库中的第一条记录（最多只有一条信息）
                        overwrite_first_event(now, 'listened', json.dumps({"listened": text}, ensure_ascii=False))
                    # GUI 日志：输出“识别”
                    try:
                        if on_event:
                            on_event('listened', {"text": text})
                    except Exception:
                        pass
                    if enable_mqtt:
                        publish_json(mqtt_client, TOPIC_ASR_TEXT, {"text": text, "ref_id": msg_id})
                        publish_json(mqtt_client, TOPIC_LLM_ASK, {"text": text, "ref_id": msg_id})
                    print(f'[ASR] cmd -> {text}')
                    # 处理一条指令后退出唤醒态
                    awake = False
                    time.sleep(0.1)
                    continue

            # 不启用唤醒词：保持直通；为了契合“最多一条信息”的要求，也采用覆盖写入
            msg_id = None
            if enable_sqlite:
                now = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                overwrite_first_event(now, 'listened', json.dumps({"listened": text}, ensure_ascii=False))
            # GUI 日志：输出“识别”
            try:
                if on_event:
                    on_event('listened', {"text": text})
            except Exception:
                pass
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


def main():
    # 兼容原先的独立运行入口
    stop_event = threading.Event()
    try:
        listen_loop(stop_event)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()

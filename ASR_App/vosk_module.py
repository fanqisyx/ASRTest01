# 独立副本：ASR 使用
import threading
import datetime
from vosk import Model, KaldiRecognizer
import pyaudio
import json
import audioop

_vosk_model_cache = {}

def print_with_time(msg):
    t = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{t}] {msg}")

def get_vosk_model(model_path):
    global _vosk_model_cache
    if model_path in _vosk_model_cache:
        return _vosk_model_cache[model_path]
    print_with_time(f"正在加载Vosk模型: {model_path}")
    model = Model(model_path)
    _vosk_model_cache[model_path] = model
    print_with_time("Vosk模型加载完成")
    return model

def _list_input_devices(pa: pyaudio.PyAudio):
    devices = []
    count = pa.get_device_count()
    for i in range(count):
        try:
            info = pa.get_device_info_by_index(i)
            if info.get('maxInputChannels', 0) > 0:
                devices.append(info)
        except Exception:
            continue
    return devices

def recognize_speech(model_path=None, stop_event: threading.Event = None, discard_event: threading.Event = None, on_model_loading=None, on_model_ready=None):
    if model_path is None:
        model_path = r"E:\\AITools\\model\\Vosk\\vosk-model-cn-0.22"
    if on_model_loading:
        on_model_loading()
    model = get_vosk_model(model_path)
    if on_model_ready:
        on_model_ready()
    pa = pyaudio.PyAudio()
    chosen_stream = None
    chosen_rate = None
    chosen_device = None
    try:
        devices = _list_input_devices(pa)
        device_indices = [None] + [d.get('index') for d in devices]
        sample_rates = [16000, 48000, 44100]
        buffers = [1024, 2048, 512]
        last_err = None
        for dev_idx in device_indices:
            for rate in sample_rates:
                for buf in buffers:
                    try:
                        stream = pa.open(
                            format=pyaudio.paInt16,
                            channels=1,
                            rate=rate,
                            input=True,
                            frames_per_buffer=buf,
                            input_device_index=dev_idx
                        )
                        chosen_stream = stream
                        chosen_rate = rate
                        chosen_device = dev_idx
                        break
                    except Exception as e:
                        last_err = e
                        continue
                if chosen_stream:
                    break
            if chosen_stream:
                break
        if not chosen_stream:
            print_with_time("[ERROR] 无法打开麦克风输入流")
            raise OSError(f"无法打开任一输入设备: {last_err}")
        rec = KaldiRecognizer(model, chosen_rate)
        chosen_stream.start_stream()
        dev_name = None
        try:
            if chosen_device is None:
                dev_name = pa.get_default_input_device_info().get('name')
            else:
                dev_name = pa.get_device_info_by_index(chosen_device).get('name')
        except Exception:
            dev_name = str(chosen_device)
        print_with_time(f"已打开麦克风: device={dev_name} rate={chosen_rate}Hz buffer={chosen_stream._frames_per_buffer}")
        print_with_time("请开始说话...")
    except Exception:
        try:
            pa.terminate()
        except Exception:
            pass
        raise
    text = ''
    partial_text = ''
    last_voice_time = datetime.datetime.now()
    silence_timeout = 3.0  # 秒；静音超过该时间且有partial，返回partial
    amp_threshold = 200  # 简单音量阈值（0~32767），用于辅助判断有无发声
    start_time = datetime.datetime.now()
    max_listen_time = 12.0  # 单次最长监听秒数，避免无限等待
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            data = chosen_stream.read(1024, exception_on_overflow=False)
            if discard_event is not None and discard_event.is_set():
                continue
            # 音量更新：有明显能量时刷新最后发声时间
            try:
                amp = audioop.rms(data, 2)  # 2字节宽度（16bit）
                if amp >= amp_threshold:
                    last_voice_time = datetime.datetime.now()
            except Exception:
                pass
            # 只要有输入就认为有声音活动
            now = datetime.datetime.now()
            # 处理识别
            if rec.AcceptWaveform(data):
                result = rec.Result()
                try:
                    text = json.loads(result).get('text', '')
                except Exception:
                    text = ''
                # 如果是空文本，继续监听，避免立刻退出导致频繁重开麦克风
                if text:
                    break
                else:
                    continue
            else:
                try:
                    p = json.loads(rec.PartialResult() or '{}')
                    pt = (p.get('partial') or '').strip()
                    if pt:
                        partial_text = pt
                        last_voice_time = now
                except Exception:
                    pass
                # 静音超时：如果超过阈值且有partial，返回它
                if partial_text:
                    if (now - last_voice_time).total_seconds() >= silence_timeout:
                        text = partial_text
                        break
            # 全局超时，仍无结果则退出（返回空）
            if (now - start_time).total_seconds() >= max_listen_time:
                break
    finally:
        try:
            if chosen_stream:
                chosen_stream.stop_stream()
                chosen_stream.close()
        except Exception:
            pass
        try:
            pa.terminate()
        except Exception:
            pass
    return text

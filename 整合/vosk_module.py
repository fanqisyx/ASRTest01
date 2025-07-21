import threading
import datetime
# Vosk语音识别模块
from vosk import Model, KaldiRecognizer
import pyaudio
import json


_vosk_model_cache = {}

def print_with_time(msg):
    t = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{t}] {msg}")

def get_vosk_model(model_path):
    """
    只加载一次模型，后续复用。
    """
    global _vosk_model_cache
    if model_path in _vosk_model_cache:
        return _vosk_model_cache[model_path]
    print_with_time(f"正在加载Vosk模型: {model_path}")
    model = Model(model_path)
    _vosk_model_cache[model_path] = model
    print_with_time("Vosk模型加载完成")
    return model

def recognize_speech(model_path=None, stop_event: threading.Event = None, discard_event: threading.Event = None, on_model_loading=None, on_model_ready=None):
    """
    监听麦克风，识别一段语音，返回识别到的文本（只返回一次结果）。
    model_path: 可选，指定Vosk模型路径。
    stop_event: 可选，外部中断事件，设置后可强制中断收音。
    discard_event: 可选，TTS期间为True时丢弃所有音频数据，不做识别。
    on_model_loading: 可选，模型加载前回调（如切换指示灯）
    on_model_ready: 可选，模型加载后回调（如切换指示灯）
    """
    if model_path is None:
        model_path = r"E:\AITools\model\Vosk\vosk-model-cn-0.22"
    if on_model_loading:
        on_model_loading()
    model = get_vosk_model(model_path)
    if on_model_ready:
        on_model_ready()
    rec = KaldiRecognizer(model, 16000)
    stream = pyaudio.PyAudio().open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)
    stream.start_stream()
    print_with_time("请开始说话...")
    text = ''
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            data = stream.read(1024, exception_on_overflow=False)
            if discard_event is not None and discard_event.is_set():
                continue  # TTS期间丢弃音频数据
            if rec.AcceptWaveform(data):
                result = rec.Result()
                try:
                    text = json.loads(result).get('text', '')
                except Exception:
                    text = ''
                break
    finally:
        stream.stop_stream()
        stream.close()
    return text

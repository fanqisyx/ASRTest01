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

def _list_input_devices(pa: pyaudio.PyAudio):
    """列出可用输入设备信息。"""
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
    # 尝试打开麦克风（多策略回退），并匹配识别器采样率
    pa = pyaudio.PyAudio()
    chosen_stream = None
    chosen_rate = None
    chosen_device = None
    # 策略组合：设备索引（默认->每个输入设备） x 采样率 x buffer
    try:
        devices = _list_input_devices(pa)
        # 尝试默认输入设备先
        device_indices = [None]
        for d in devices:
            device_indices.append(d.get('index'))
        # 常见可用采样率（含16k以兼容模型、以及常见硬件原生率）
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
            # 打印设备清单帮助诊断
            print_with_time("[ERROR] 无法打开麦克风输入流，尝试的采样率/缓冲均失败。可用输入设备如下：")
            for d in devices:
                print_with_time(f" - idx={d.get('index')} name={d.get('name')} api={d.get('hostApi')} maxIn={d.get('maxInputChannels')} defaultSR={d.get('defaultSampleRate')}")
            raise OSError(f"无法打开任一输入设备: {last_err}")

        # 与所选采样率匹配的识别器
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
        # 失败时清理 PyAudio
        try:
            pa.terminate()
        except Exception:
            pass
        raise
    text = ''
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            data = chosen_stream.read(1024, exception_on_overflow=False)
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

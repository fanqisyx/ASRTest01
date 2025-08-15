import threading
import queue
import traceback
import pyttsx3
from logger_util import info as logi, warning as logw, exception as logx


class TTSManager:
    def __init__(self):
        # 引擎实例与并发保护
        self._engine = None
        self._engine_lock = threading.RLock()
        self._reset_requested = threading.Event()

        # 工作线程与队列
        self._tts_thread = None
        self._tts_queue = queue.Queue()
        self._stop_event = threading.Event()
        self._current_task = None

        self._init_engine()
        self._start_worker()

    def _init_engine(self):
        """仅初始化一次 TTS 引擎，并优先选择中文语音。"""
        with self._engine_lock:
            if self._engine is None:
                try:
                    engine = pyttsx3.init()
                    logi("TTS_ENGINE_INIT_OK")
                    # 尝试选择中文语音
                    try:
                        voices = engine.getProperty('voices')
                        for voice in voices:
                            if any(k in voice.name.lower() for k in ["chinese", "huihui", "lili", "ting-ting"]):
                                engine.setProperty('voice', voice.id)
                                logi(f"TTS_VOICE_SELECTED name={voice.name}")
                                break
                    except Exception:
                        logw("TTS_VOICE_ENUM_FAIL")
                    self._engine = engine
                except Exception as e:
                    logx(f"TTS_ENGINE_INIT_FAIL: {e}")
                    self._engine = None

    def _start_worker(self):
        """启动 TTS 工作线程。"""
        if self._tts_thread is None or not self._tts_thread.is_alive():
            self._tts_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._tts_thread.start()
            logi("TTS_WORKER_THREAD_STARTED")

    def _request_engine_reset(self):
        """标记需要在安全点重建引擎（由 worker 执行）。"""
        self._reset_requested.set()

    def _rebuild_engine_if_needed(self):
        """如收到重建请求，则在 worker 安全点重建引擎。"""
        if self._reset_requested.is_set():
            with self._engine_lock:
                try:
                    if self._engine is not None:
                        try:
                            self._engine.stop()
                            logi("TTS_ENGINE_STOP_BEFORE_RESET")
                        except Exception:
                            logw("TTS_ENGINE_STOP_BEFORE_RESET_FAIL")
                finally:
                    self._engine = None
                    self._reset_requested.clear()
                    self._init_engine()
                    logi("TTS_ENGINE_RESET_DONE")

    def _worker_loop(self):
        """TTS 工作循环，避免并发问题。"""
        while not self._stop_event.is_set():
            try:
                task = self._tts_queue.get(timeout=1)
                if task is None:
                    break
                text, callback, stop_event = task
                self._current_task = task

                if stop_event and stop_event.is_set():
                    logw("TTS_SKIP_DUE_TO_STOP_EVENT")
                    continue

                local_engine = None
                with self._engine_lock:
                    local_engine = self._engine
                if local_engine:
                    try:
                        logi(f"TTS_RUN start len={len(text)}")
                        local_engine.say(text)
                        local_engine.runAndWait()
                        logi("TTS_RUN done")
                    except Exception as e:
                        logx(f"TTS_RUN_EXCEPTION: {e}")
                        self._request_engine_reset()

                if callback:
                    try:
                        callback()
                    except Exception as e:
                        logx(f"TTS_CALLBACK_EXCEPTION: {e}")

                self._rebuild_engine_if_needed()

            except queue.Empty:
                continue
            except Exception as e:
                logx(f"TTS_WORKER_LOOP_EXCEPTION: {e}")
            finally:
                self._current_task = None

    def speak(self, text: str, callback=None, stop_event=None):
        """添加 TTS 任务到队列。"""
        if not self._stop_event.is_set():
            self._tts_queue.put((text, callback, stop_event))
            logi(f"TTS_QUEUE_PUSH len={len(text)}")

    def stop_current(self):
        """停止当前 TTS 播报并请求重建引擎。"""
        while not self._tts_queue.empty():
            try:
                self._tts_queue.get_nowait()
            except queue.Empty:
                break
        with self._engine_lock:
            if self._engine:
                try:
                    self._engine.stop()
                    logi("TTS_ENGINE_STOP_CALLED")
                except Exception:
                    logw("TTS_ENGINE_STOP_FAIL")
        self._request_engine_reset()
        logi("TTS_REQUEST_ENGINE_RESET")

    def shutdown(self):
        """关闭 TTS 管理器。"""
        self._stop_event.set()
        self._tts_queue.put(None)
        if self._tts_thread:
            self._tts_thread.join(timeout=2)


# 全局 TTS 管理器实例
_tts_manager = TTSManager()


def speak_text_safe(text, callback=None, stop_event=None):
    """安全的 TTS 播报函数。"""
    _tts_manager.speak(text, callback, stop_event)


def stop_tts():
    """停止当前 TTS。"""
    _tts_manager.stop_current()


def speak_text(text):
    """
    用 TTS 朗读文本，优先使用中文语音。
    保持向后兼容。
    """
    speak_text_safe(text)


def speak_text_interruptable(text, stop_event):
    """
    用 TTS 朗读文本，支持 stop_event.set() 时中断。
    使用改进的 TTS 管理器实现。
    """
    try:
        speak_text_safe(text, stop_event=stop_event)
    except Exception as e:
        tb = traceback.format_exc()
        logx(f"speak_text_interruptable异常: {e}\n{tb}")
        with open("fatal_error.log", "a", encoding="utf-8") as f:
            f.write(f"[FATAL] speak_text_interruptable异常: {e}\n{tb}\n")

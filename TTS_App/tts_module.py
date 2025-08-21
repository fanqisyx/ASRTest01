# 独立副本：TTS 使用
import threading
import queue
import traceback
import pyttsx3

class TTSManager:
    def __init__(self):
        self._engine = None
        self._engine_lock = threading.RLock()
        self._reset_requested = threading.Event()
        self._tts_thread = None
        self._tts_queue = queue.Queue()
        self._stop_event = threading.Event()
        self._current_task = None
        self._init_engine()
        self._start_worker()

    def _init_engine(self):
        with self._engine_lock:
            if self._engine is None:
                try:
                    engine = pyttsx3.init()
                    try:
                        voices = engine.getProperty('voices')
                        for voice in voices:
                            if any(k in voice.name.lower() for k in ["chinese", "huihui", "lili", "ting-ting"]):
                                engine.setProperty('voice', voice.id)
                                break
                    except Exception:
                        pass
                    self._engine = engine
                except Exception:
                    self._engine = None

    def _start_worker(self):
        if self._tts_thread is None or not self._tts_thread.is_alive():
            self._tts_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._tts_thread.start()

    def _request_engine_reset(self):
        self._reset_requested.set()

    def _rebuild_engine_if_needed(self):
        if self._reset_requested.is_set():
            with self._engine_lock:
                try:
                    if self._engine is not None:
                        try:
                            self._engine.stop()
                        except Exception:
                            pass
                finally:
                    self._engine = None
                    self._reset_requested.clear()
                    self._init_engine()

    def _worker_loop(self):
        while not self._stop_event.is_set():
            try:
                task = self._tts_queue.get(timeout=1)
                if task is None:
                    break
                text, callback, stop_event = task
                self._current_task = task
                if stop_event and stop_event.is_set():
                    continue
                local_engine = None
                with self._engine_lock:
                    local_engine = self._engine
                if local_engine:
                    try:
                        local_engine.say(text)
                        local_engine.runAndWait()
                    except Exception:
                        self._request_engine_reset()
                if callback:
                    try:
                        callback()
                    except Exception:
                        pass
                self._rebuild_engine_if_needed()
            except queue.Empty:
                continue
            except Exception:
                pass
            finally:
                self._current_task = None

    def speak(self, text: str, callback=None, stop_event=None):
        if not self._stop_event.is_set():
            self._tts_queue.put((text, callback, stop_event))

    def stop_current(self):
        while not self._tts_queue.empty():
            try:
                self._tts_queue.get_nowait()
            except queue.Empty:
                break
        with self._engine_lock:
            if self._engine:
                try:
                    self._engine.stop()
                except Exception:
                    pass
        self._request_engine_reset()

    def shutdown(self):
        self._stop_event.set()
        self._tts_queue.put(None)
        if self._tts_thread:
            self._tts_thread.join(timeout=2)

_tts_manager = TTSManager()

def speak_text_safe(text, callback=None, stop_event=None):
    _tts_manager.speak(text, callback, stop_event)

def stop_tts():
    _tts_manager.stop_current()

def speak_text(text):
    speak_text_safe(text)

def speak_text_interruptable(text, stop_event):
    try:
        speak_text_safe(text, stop_event=stop_event)
    except Exception:
        tb = traceback.format_exc()
        with open("fatal_error.log", "a", encoding="utf-8") as f:
            f.write(f"[FATAL] speak_text_interruptable异常\n{tb}\n")

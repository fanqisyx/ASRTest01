import threading
import queue
import time
import traceback
from typing import Optional
import pyttsx3


class TTSManager:
    def __init__(self):
        # pyttsx3 引擎实例（仅在 _engine_lock 保护下读/写）
        self._engine = None
        # 引擎并发保护锁：避免 stop()/重建 与 worker 并发操作引擎产生竞态
        self._engine_lock = threading.RLock()
        # 请求重建引擎的标志：由 stop_current() 或异常触发，worker 在安全点执行重建
        self._reset_requested = threading.Event()
        self._tts_thread = None
        self._tts_queue = queue.Queue()
        self._stop_event = threading.Event()
        self._current_task = None
        self._init_engine()
        self._start_worker()
    
    def _init_engine(self):
        """只初始化一次TTS引擎"""
        with self._engine_lock:
            if self._engine is None:
                try:
                    engine = pyttsx3.init()
                    # 尝试优先选择中文语音
                    try:
                        voices = engine.getProperty('voices')
                        for voice in voices:
                            if any(keyword in voice.name.lower() for keyword in ["chinese", "huihui", "lili", "ting-ting"]):
                                engine.setProperty('voice', voice.id)
                                print(f"[TTS] 选中voice: {voice.name}")
                                break
                    except Exception:
                        # 语音获取失败不影响引擎可用性
                        pass
                    self._engine = engine
                except Exception as e:
                    print(f"[TTS] 初始化引擎失败: {e}")
                    self._engine = None
    
    def _start_worker(self):
        """启动TTS工作线程"""
        if self._tts_thread is None or not self._tts_thread.is_alive():
            self._tts_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._tts_thread.start()
    
    def _request_engine_reset(self):
        """标记需要在安全点重建引擎（由worker执行）。"""
        self._reset_requested.set()

    def _rebuild_engine_if_needed(self):
        """如收到重建请求，则在worker安全点重建引擎。"""
        if self._reset_requested.is_set():
            with self._engine_lock:
                try:
                    # 优先尝试停止当前引擎（若仍存在）
                    if self._engine is not None:
                        try:
                            self._engine.stop()
                        except Exception:
                            pass
                finally:
                    # 重新创建引擎
                    self._engine = None
                    self._reset_requested.clear()
                    self._init_engine()

    def _worker_loop(self):
        """TTS工作循环，避免并发问题"""
        while not self._stop_event.is_set():
            try:
                task = self._tts_queue.get(timeout=1)
                if task is None:  # 退出信号
                    break
                
                text, callback, stop_event = task
                self._current_task = task
                
                if stop_event and stop_event.is_set():
                    continue
                
                # 执行TTS播报
                local_engine = None
                with self._engine_lock:
                    local_engine = self._engine
                if local_engine:
                    try:
                        print(f"[TTS] 开始播报: {text}")
                        # 注意：不在锁内长时间阻塞，允许 stop() 并发打断
                        local_engine.say(text)
                        local_engine.runAndWait()
                        print(f"[TTS] 播报完成: {text}")
                    except Exception as e:
                        print(f"[TTS] 播报异常: {e}")
                        # 请求在安全点重建引擎
                        self._request_engine_reset()
                
                # 调用完成回调
                if callback:
                    try:
                        callback()
                    except Exception as e:
                        print(f"[TTS] 回调异常: {e}")
                
                # 播放完成后在安全点处理引擎重建
                self._rebuild_engine_if_needed()
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[TTS] 工作循环异常: {e}")
            finally:
                self._current_task = None
    
    def speak(self, text: str, callback=None, stop_event=None):
        """添加TTS任务到队列"""
        if not self._stop_event.is_set():
            self._tts_queue.put((text, callback, stop_event))
    
    def stop_current(self):
        """停止当前TTS播报"""
        # 清空队列
        while not self._tts_queue.empty():
            try:
                self._tts_queue.get_nowait()
            except queue.Empty:
                break
        
        # 尝试停止引擎当前播放（允许在worker线程中的 runAndWait 被打断）
        with self._engine_lock:
            if self._engine:
                try:
                    self._engine.stop()
                except Exception:
                    pass
        # 请求在安全点重建引擎，避免与worker并发直接替换引擎
        self._request_engine_reset()
    
    def shutdown(self):
        """关闭TTS管理器"""
        self._stop_event.set()
        self._tts_queue.put(None)  # 发送退出信号
        if self._tts_thread:
            self._tts_thread.join(timeout=2)


# 全局TTS管理器实例
_tts_manager = TTSManager()

def speak_text_safe(text, callback=None, stop_event=None):
    """安全的TTS播报函数"""
    _tts_manager.speak(text, callback, stop_event)

def stop_tts():
    """停止当前TTS"""
    _tts_manager.stop_current()

def speak_text(text):
    """
    用TTS朗读文本，优先使用中文语音。
    保持向后兼容。
    """
    speak_text_safe(text)

def speak_text_interruptable(text, stop_event):
    """
    用TTS朗读文本，支持stop_event.set()时中断。
    使用改进的TTS管理器实现。
    """
    try:
        speak_text_safe(text, stop_event=stop_event)
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[FATAL] speak_text_interruptable异常: {e}\n{tb}")
        with open("fatal_error.log", "a", encoding="utf-8") as f:
            f.write(f"[FATAL] speak_text_interruptable异常: {e}\n{tb}\n")

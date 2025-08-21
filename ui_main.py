from PyQt5.QtCore import pyqtSignal
import datetime

import datetime
import threading
import time
import json
import os
import re
import queue
from PyQt5 import QtWidgets, QtCore, QtGui
from logger_util import debug as logd, info as logi, warning as logw, error as loge, exception as logx
from vosk_module import recognize_speech
from tts_module import speak_text, speak_text_safe
try:
    from tts_module import speak_text_interruptable
except ImportError:
    def speak_text_interruptable(text, stop_event):
        speak_text(text)
from lmstudio_module import query_lmstudio
from config import Config
from pypinyin import lazy_pinyin

def log_with_time(msg):
    t = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{t}] {msg}")
    try:
        logi(msg)
    except Exception:
        pass


class LightIndicator(QtWidgets.QWidget):
    """状态指示灯组件"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self.is_active = False
    
    def set_active(self, active):
        self.is_active = active
        self.update()
    
    def paintEvent(self, event):
        from PyQt5.QtGui import QPainter, QColor
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = "#00FF00" if self.is_active else "#AAAAAA"
        painter.setBrush(QColor(color))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawEllipse(0, 0, 16, 16)


# MainWindow主界面类，包含所有主流程和UI逻辑
class MainWindow(QtWidgets.QWidget):
    tts_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)  # 新增：通用状态文本信号（主线程追加显示）
    def __init__(self):
        super().__init__()
        log_with_time(f"[TTS] MainWindow.__init__: self id={id(self)}")
        # 强制使用队列连接确保跨线程信号正常工作
        from PyQt5.QtCore import Qt
        connection_result = self.tts_signal.connect(self._tts_on_main_thread, Qt.QueuedConnection)
        # 连接状态信号到append_text，确保线程安全UI更新
        self.status_signal.connect(self.append_text, Qt.QueuedConnection)
        log_with_time(f"[TTS] MainWindow.__init__: signal connect result={connection_result} (使用QueuedConnection)")
        self.setWindowTitle("语音助手整合Demo")
        self.voice_queue = queue.Queue()
        self.voice_history = []
        self.listening = False
        self.processing = False
        self._processing_lock = threading.Lock()  # 新增：防止并发处理
        self.listen_pause = threading.Event()
        self.listen_stop_event = threading.Event()
        self.listen_discard_event = threading.Event()
        self.tts_stop_event = threading.Event()
        self.process_lock = threading.Lock()
        self.autostop_timer = None
        self.init_ui()
        self.load_config()
        # 初始化action_damo.txt文件
        self.init_action_damo_file()
        # 启动时清空model_command.txt
        self.clear_model_command_file()
        # 初始化串行TTS队列
        self._init_tts_worker()
        # 测试信号槽连接
        self.test_signal_connection()
        # 语音输入去重控制
        self._last_voice_text = None
        self._last_voice_time = 0
        self._vosk_loaded = False  # 新增：Vosk模型是否已加载完成标志

    def clear_model_command_file(self):
        try:
            with open("model_command.txt", "w", encoding="utf-8") as f:
                f.write("")
            log_with_time("[系统] model_command.txt已在启动时清空")
        except Exception as e:
            log_with_time(f"[系统] 清空model_command.txt失败: {e}")

    def _compute_tts_delay(self, char_count):
        """根据设置计算TTS结束后恢复收音的延迟"""
        # tts_delay_mode: 'dynamic' or 'fixed'
        if getattr(self, 'tts_delay_mode', 'fixed') == 'fixed':
            try:
                return max(0, float(getattr(self, 'tts_fixed_delay', 3)))
            except Exception:
                return 3.0
        # 动态：字数/速度 + 0.5s缓冲
        chars_per_second = 200 / 60  # 约3.33/秒
        return char_count / chars_per_second + 0.5

    def _safe_speak(self, text):
        """阻塞方式安全播报：使用pyttsx3全局TTS队列并等待完成，避免PowerShell策略/转义问题"""
        try:
            from tts_module import speak_text_safe
            done = threading.Event()
            def _cb():
                done.set()
            speak_text_safe(text, callback=_cb)
            # 等待播报完成（最长120秒，避免死等）
            finished = done.wait(timeout=120)
            if not finished:
                log_with_time(f"[TTS] _safe_speak: 播报等待超时: {text[:40]}")
            else:
                log_with_time(f"[TTS] _safe_speak: 播报完成: {text[:40] + ('...' if len(text)>40 else '')}")
        except Exception as e:
            log_with_time(f"[TTS] _safe_speak: 异常: {e}")
            try:
                import winsound
                winsound.MessageBeep()
            except Exception:
                pass

    # ---- 串行TTS队列相关 ----
    def _init_tts_worker(self):
        import heapq
        self._tts_pq_lock = threading.Lock()
        self._tts_pq = []  # (priority, seq, text)
        self._tts_seq = 0
        self._tts_event = threading.Event()
        self._tts_worker_thread = threading.Thread(target=self._tts_worker, daemon=True)
        self._tts_worker_thread.start()
        log_with_time("[TTS] 串行TTS工作线程已启动")
        try:
            logi("[BOOT] TTS worker started")
        except Exception:
            pass

    def _enqueue_tts(self, text, priority=False):
        """加入TTS任务。priority=True用于JSON确认优先播报"""
        import heapq
        with self._tts_pq_lock:
            self._tts_seq += 1
            prio = 0 if priority else 1
            heapq.heappush(self._tts_pq, (prio, self._tts_seq, text))
            self._tts_event.set()
        snippet = (text[:200] + '...') if len(text) > 200 else text
        log_with_time(f"[TTS] 入队: prio={prio} len={len(text)} text={snippet}")
        try:
            logi(f"TTS_ENQUEUE prio={prio} len={len(text)}")
        except Exception:
            pass

    def _tts_worker(self):
        import heapq
        while True:
            self._tts_event.wait()
            while True:
                with self._tts_pq_lock:
                    if not self._tts_pq:
                        self._tts_event.clear()
                        break
                    prio, seq, text = heapq.heappop(self._tts_pq)
                try:
                    # 播放前暂停收音
                    self.listen_pause.set()
                    self.set_status_light(False)
                    logi(f"TTS_START len={len(text)}")
                    self._safe_speak(text)
                    logi("TTS_END")
                    delay = self._compute_tts_delay(len(text))
                    log_with_time(f"[TTS] 播放完成，延迟{delay:.2f}s后恢复收音")
                    logi(f"TTS_DELAY {delay:.2f}s")
                    time.sleep(delay)
                except Exception as e:
                    log_with_time(f"[TTS] _tts_worker异常: {e}")
                    logx("TTS_WORKER_EXCEPTION")
                finally:
                    self.listen_pause.clear()
                    if self.listening:
                        self.set_status_light(True)
                    # 仅在完成一条TTS后（而不是全部清空后）重启倒计时
                    try:
                        self._start_autostop_timer()
                    except Exception as e:
                        log_with_time(f"[TTS] 重启倒计时异常: {e}")

    def _pause_listening(self):
        """暂停语音识别"""
        self.listen_discard_event.set()
        self.listen_pause.set()
        self.set_status_light(False)
        log_with_time("[DEBUG] 语音识别已暂停")

    def _resume_listening(self):
        """恢复语音识别"""
        self.listen_discard_event.clear()
        self.listen_pause.clear()
        if self.listening:
            self.set_status_light(True)
            try:
                self._start_autostop_timer()
            except Exception as e:
                log_with_time(f"[ERROR] 恢复监听时启动定时器失败: {e}")
        log_with_time("[DEBUG] 语音识别已恢复")

    def _update_display(self, thinking, answer):
        """更新界面显示"""
        def nowstr():
            return datetime.datetime.now().strftime("%H:%M:%S")
        
        if thinking:
            msg_think = f"[{nowstr()}] [思考] {thinking}"
            self.append_text(msg_think)
            log_with_time(f"[思考] {thinking}")
        
        msg_ai = f"[{nowstr()}] [AI] {answer}"
        self.append_text(msg_ai)
        log_with_time(f"[AI] {answer}")

    def _prepare_tts_text(self, answer):
        """准备TTS播报文本，处理JSON命令"""
        tts_text = answer
        try:
            parsed = json.loads(answer)
            # 为JSON添加时间ID
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            enhanced_json = {
                "id": current_time,
                **parsed  # 将原始JSON内容合并
            }
            
            # 检查是否包含"kaishidamo"键
            if "kaishidamo" in parsed:
                # 检查值是否为"1"
                if parsed["kaishidamo"] == "1":
                    # 写入action_damo_.txt文件
                    enhanced_json_str = json.dumps(enhanced_json, ensure_ascii=False, indent=2)
                    with open("action_damo.txt", "w", encoding="utf-8") as f:
                        f.write(enhanced_json_str)
                    tts_text = "开始打磨命令已收到"
                    log_with_time(f"[DEBUG] 检测到开始打磨指令，已添加时间ID({current_time})并写入action_damo_.txt")
                else:
                    pass  # kaishidamo值不是"1"，不处理
            else:
                # 写入增强后的JSON到model_command.txt
                enhanced_json_str = json.dumps(enhanced_json, ensure_ascii=False, indent=2)
                with open("model_command.txt", "w", encoding="utf-8") as f:
                    f.write(enhanced_json_str)
                tts_text = "命令已收到"
                log_with_time(f"[DEBUG] answer为JSON，已添加时间ID({current_time})并写入model_command.txt，仅播报命令已收到")
        except Exception:
            pass  # 不是JSON，正常处理
        return tts_text

    def _execute_tts_with_state_management(self, tts_text):
        """执行TTS播报并管理状态"""
        def tts_completion_callback():
            """TTS完成后的回调"""
            try:
                # 估算额外等待时间
                time.sleep(0.5)
                
                # 恢复语音识别状态
                self._resume_listening()
                
                log_with_time("[DEBUG] TTS播报完成，状态已恢复")
            except Exception as e:
                log_with_time(f"[ERROR] TTS回调异常: {e}")
        
        # 使用改进的TTS管理器
        from tts_module import speak_text_safe
        speak_text_safe(tts_text, callback=tts_completion_callback)
    
    def test_signal_connection(self):
        """测试信号槽连接是否正常"""
        log_with_time(f"[TTS] test_signal_connection: 开始测试信号槽, self id={id(self)}")
        try:
            self.tts_signal.emit("测试信号")
            log_with_time(f"[TTS] test_signal_connection: 测试信号已发出")
        except Exception as e:
            log_with_time(f"[TTS] test_signal_connection: 测试信号发出异常: {e}")

    def _tts_on_main_thread(self, text):
        from tts_module import speak_text_interruptable
        import time
        try:
            log_with_time(f"[TTS] _tts_on_main_thread: 进入函数, text={text}, self id={id(self)}")
            log_with_time("[TTS] _tts_on_main_thread: 设置listen_pause，暂停收音")
            self.listen_pause.set()
            log_with_time("[TTS] _tts_on_main_thread: 调用speak_text_interruptable")
            speak_text_interruptable(text, self.tts_stop_event)
            log_with_time("[TTS] _tts_on_main_thread: speak_text_interruptable返回，准备估算延迟")
            # 估算TTS朗读时长
            char_count = len(text)
            estimated = self._compute_tts_delay(char_count)
            log_with_time(f"[TTS] _tts_on_main_thread: 朗读结束，延迟{estimated:.2f}秒后恢复收音")
            time.sleep(estimated)
            log_with_time("[TTS] _tts_on_main_thread: 延迟结束，准备恢复收音")
            self.listen_pause.clear()
            log_with_time("[TTS] _tts_on_main_thread: 已恢复收音")
            # 确保状态指示灯正确更新
            if self.listening:
                self.set_status_light(True)
                log_with_time("[TTS] _tts_on_main_thread: 收音状态指示灯已更新")
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            log_with_time(f"[TTS] _tts_on_main_thread: 异常: {e}\n{tb}")

    # 以下方法直接复用原SettingsDialog的相关方法
    def init_ui(self):
        self.setWindowTitle("语音助手整合Demo")
        main_layout = QtWidgets.QHBoxLayout()

        # 左侧：对话区
        left_layout = QtWidgets.QVBoxLayout()
        self.text_display = QtWidgets.QTextEdit()
        self.text_display.setReadOnly(True)
        left_layout.addWidget(self.text_display)

        # 手动输入测试区域
        manual_layout = QtWidgets.QHBoxLayout()
        self.manual_input = QtWidgets.QLineEdit()
        self.manual_input.setPlaceholderText("手动输入测试内容，回车或点击发送")
        self.manual_input.returnPressed.connect(self.send_manual_input)
        self.manual_send_btn = QtWidgets.QPushButton("发送(测试)")
        self.manual_send_btn.clicked.connect(self.send_manual_input)
        manual_layout.addWidget(self.manual_input)
        manual_layout.addWidget(self.manual_send_btn)
        left_layout.addLayout(manual_layout)

        btn_layout = QtWidgets.QHBoxLayout()
        self.btn_start = QtWidgets.QPushButton("开始聆听")
        self.btn_start.clicked.connect(self.start_listen)
        self.btn_stop = QtWidgets.QPushButton("停止")
        self.btn_stop.clicked.connect(self.stop_listen)
        self.btn_stop.setEnabled(False)
        self.btn_settings = QtWidgets.QPushButton("设置")
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_clear = QtWidgets.QPushButton("清空对话")
        self.btn_clear.clicked.connect(self.clear_text_display)
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        btn_layout.addWidget(self.btn_settings)
        btn_layout.addWidget(self.btn_clear)
        left_layout.addLayout(btn_layout)

        # 右侧：语音队列窗口
        right_layout = QtWidgets.QVBoxLayout()
        status_layout = QtWidgets.QHBoxLayout()
        self.label_status = QtWidgets.QLabel("收音状态：")
        self.status_light = QtWidgets.QLabel()
        self.set_status_light(False)
        status_layout.addWidget(self.label_status)
        status_layout.addWidget(self.status_light)
        status_layout.addStretch()
        right_layout.addLayout(status_layout)

        self.label_queue = QtWidgets.QLabel("语音队列：")
        self.label_countdown = QtWidgets.QLabel("")
        queue_row = QtWidgets.QHBoxLayout()
        queue_row.addWidget(self.label_queue)
        queue_row.addWidget(self.label_countdown)
        queue_row.addStretch()
        right_layout.addLayout(queue_row)
        self.list_queue = QtWidgets.QListWidget()
        right_layout.addWidget(self.list_queue)
        right_layout.addStretch()

        main_layout.addLayout(left_layout, 3)
        main_layout.addLayout(right_layout, 1)
        self.setLayout(main_layout)

    def set_status_light(self, listening):
        color = "#00FF00" if listening else "#AAAAAA"
        from PyQt5.QtGui import QPixmap, QPainter, QColor
        pix = QPixmap(16, 16)
        pix.fill(QtCore.Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawEllipse(0, 0, 16, 16)
        painter.end()
        self.status_light.setPixmap(pix)

    def clear_text_display(self):
        self.text_display.clear()

    def load_config(self):
        config = SettingsDialog.read_config()
        self.lmstudio_url = config.get("lmstudio_url", "http://localhost:1234/v1/chat/completions")
        self.lmstudio_model = config.get("lmstudio_model", "your-model-name")
        self.vosk_model_path = config.get("vosk_model_path", "E:/AITools/model/Vosk/vosk-model-cn-0.22")
        self.enable_wakeword = bool(config.get("enable_wakeword", False))
        self.wakeword = config.get("wakeword", "你好小明")
        self.enable_autostop = config.get("enable_autostop", False)
        self.autostop_time = int(config.get("autostop_time", 30))
        self.block_wakeword_after_wake = config.get("block_wakeword_after_wake", True)
        self.no_think = bool(config.get("no_think", False))  # 新增: No Think配置
        self.tts_delay_mode = config.get("tts_delay_mode", "fixed")  # 'fixed' or 'dynamic'
        self.tts_fixed_delay = float(config.get("tts_fixed_delay", 3))
        self.wake_state = 'idle'

    def open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            dlg.save_config()
            self.load_config()
            msg = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] [系统] 设置已保存"
            self.text_display.append(msg)
            log_with_time("[系统] 设置已保存")

    def append_text(self, msg):
        self.text_display.append(msg)

    # 新增：手动输入发送逻辑
    def send_manual_input(self):
        text = self.manual_input.text().strip()
        if not text:
            return
        if not self.listening:
            # 未开始监听时提示
            nowstr = datetime.datetime.now().strftime('%H:%M:%S')
            self.append_text(f"[{nowstr}] [系统] 请先开始聆听后再进行手动测试。")
            return
        nowstr = datetime.datetime.now().strftime('%H:%M:%S')
        # 追加到历史 & 队列，模拟识别结果
        self.voice_history.append((nowstr, text))
        self.update_queue_list()
        self.voice_queue.put(text)
        self.manual_input.clear()
        self.process_next()

    def start_listen(self):
        import traceback
        try:
            if self.listening:
                return
            # 许可校验（调用加密文件夹的check_license）
            import importlib.util, os
            加密_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), './加密'))
            license_check_path = os.path.join(加密_dir, 'license_check.py')
            spec = importlib.util.spec_from_file_location('license_check', license_check_path)
            license_check_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(license_check_mod)
            check_license = license_check_mod.check_license
            # 许可路径和公钥路径，优先用设置页配置，否则用默认
            license_path = getattr(self, 'license_path', 'license.lic')
            pubkey_path = getattr(self, 'pubkey_path', 'public.pem')
            # 若主界面未设置，可尝试SettingsDialog默认值
            try:
                from PyQt5.QtWidgets import QApplication
                # 尝试获取设置页内容
                dlg = SettingsDialog()
                license_path = dlg.license_path_edit.text() or license_path
                pubkey_path = dlg.pubkey_path_edit.text() or pubkey_path
            except Exception:
                pass
            result = check_license(license_path, pubkey_path)
            if result['status'] == 'expired':
                QtWidgets.QMessageBox.warning(self, "许可证过期", result.get('msg', '您的许可证已过期，请联系管理员。'))
                self.listening = False
                self.processing = False
                self.set_status_light(False)
                self.btn_start.setEnabled(True)
                self.btn_stop.setEnabled(False)
                return
            with self.process_lock:
                self.processing = False
            self.tts_stop_event.clear()
            self.listening = True
            self.wake_state = 'idle'
            self.set_status_light(False)
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            msg = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] [系统] 开始聆听（{'唤醒词模式' if self.enable_wakeword else '普通模式'}）..."
            self.append_text(msg)
            log_with_time(msg)
            self.listen_thread = threading.Thread(target=self.listen_loop, daemon=True)
            self.listen_thread.start()
            if not self.enable_wakeword:
                self.process_next()
        except Exception as e:
            tb = traceback.format_exc()
            log_with_time(f"[FATAL] start_listen异常: {e}\n{tb}")
            with open("fatal_error.log", "a", encoding="utf-8") as f:
                f.write(f"[FATAL] start_listen异常: {e}\n{tb}\n")

    def stop_listen(self):
        self.listening = False
        self.processing = False
        self.tts_stop_event.set()
        
        # 停止当前TTS播报
        from tts_module import stop_tts
        stop_tts()
        
        self.set_status_light(False)
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.wake_state = 'idle'
        
        # 重置状态
        self.listen_discard_event.clear()
        self.listen_pause.clear()
        # 停止倒计时线程，清空label
        self.label_countdown.setText("")
        if hasattr(self, '_countdown_timer') and self._countdown_timer:
            self._countdown_timer.cancel()
        
        msg = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] [系统] 已停止聆听。"
        self.append_text(msg)
        log_with_time(msg)

    def _on_vosk_loading(self):
        """Vosk模型开始加载回调（仅第一次）"""
        if self._vosk_loaded:
            return
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        self.status_signal.emit(f"[{ts}] [系统] 正在加载语音识别模型...")
        log_with_time("[系统] 正在加载语音识别模型...")
        try:
            self.set_status_light(False)
        except Exception:
            pass

    def _on_vosk_ready(self):
        """Vosk模型加载完成回调（仅第一次）"""
        if self._vosk_loaded:
            return
        self._vosk_loaded = True
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        self.status_signal.emit(f"[{ts}] [系统] 语音识别模型已就绪")
        log_with_time("[系统] 语音识别模型已就绪")
        try:
            if self.listening and not self.listen_pause.is_set():
                self.set_status_light(True)
        except Exception:
            pass

    def listen_loop(self):
        import traceback
        try:
            import vosk_module
            self.set_status_light(False)
            wakeword_pinyin = self._normalize_pinyin(self.wakeword) if self.enable_wakeword else None
            while self.listening:
                if self.listen_pause.is_set():
                    time.sleep(0.1)
                    continue
                self.listen_stop_event.clear()
                self.set_status_light(True if self._vosk_loaded else False)
                # 仅在首次加载时提供回调显示加载/完成状态
                if not self._vosk_loaded:
                    text = vosk_module.recognize_speech(
                        self.vosk_model_path,
                        stop_event=self.listen_stop_event,
                        discard_event=self.listen_discard_event,
                        on_model_loading=self._on_vosk_loading,
                        on_model_ready=self._on_vosk_ready
                    )
                else:
                    text = vosk_module.recognize_speech(
                        self.vosk_model_path,
                        stop_event=self.listen_stop_event,
                        discard_event=self.listen_discard_event
                    )
                if not self.listening:
                    break
                nowstr = datetime.datetime.now().strftime('%H:%M:%S')
                # 只收到1个字时，视为噪音，丢弃
                if text and len(text.strip()) == 1:
                    continue
                if text:
                    self.voice_history.append((nowstr, text))
                    self.update_queue_list()
                # 封装入队（含去重节流）
                def try_enqueue(txt):
                    if not txt:
                        return
                    import time as _t
                    ts = _t.time()
                    norm = txt.strip()
                    # 重复抑制：完全相同且1.0秒内出现视为同一条，忽略
                    if self._last_voice_text == norm and (ts - self._last_voice_time) < 1.0:
                        log_with_time(f"[VOICE] 跳过短间隔重复: {norm}")
                        return
                    # 若队列中已经存在同文本（防止在当前处理尚未结束时再次多次识别同一句）
                    try:
                        existing = list(self.voice_queue.queue)
                        if norm in existing:
                            log_with_time(f"[VOICE] 队列已包含该文本，忽略: {norm}")
                            return
                    except Exception:
                        pass
                    # 合法入队
                    self.voice_queue.put(norm)
                    self._last_voice_text = norm
                    self._last_voice_time = ts
                    log_with_time(f"[VOICE] 入队文本: {norm}")
                    # 仅在当前未processing时启动处理线程；若正在processing则循环会自动取新任务
                    if not self.processing:
                        self.process_next()
                if self.enable_wakeword:
                    if self.wake_state == 'idle':
                        if text:
                            text_pinyin = self._normalize_pinyin(text)
                            if wakeword_pinyin and wakeword_pinyin in text_pinyin:
                                self.wake_state = 'waked'
                                self.append_text(f"[{nowstr}] [系统] 检测到唤醒词，已唤醒")
                                log_with_time("[系统] 检测到唤醒词，已唤醒")
                                self._start_autostop_timer()
                                self.listen_discard_event.set()
                                self.set_status_light(False)
                                self._safe_speak("你好！")
                                self.listen_discard_event.clear()
                                if self.listening:
                                    self.set_status_light(True)
                                if not self.block_wakeword_after_wake:
                                    try_enqueue(text)
                    elif self.wake_state == 'waked':
                        if self.block_wakeword_after_wake:
                            if text and not self.listen_discard_event.is_set():
                                try_enqueue(text)
                        else:
                            if text:
                                text_pinyin = self._normalize_pinyin(text)
                                if wakeword_pinyin and wakeword_pinyin in text_pinyin:
                                    self.append_text(f"[{nowstr}] [系统] 检测到唤醒词，已唤醒")
                                    log_with_time("[系统] 再次检测到唤醒词")
                                    self.listen_discard_event.set()
                                    self.set_status_light(False)
                                    self._safe_speak("你好！")
                                    self.listen_discard_event.clear()
                                    if self.listening:
                                        self.set_status_light(True)
                                else:
                                    if text and not self.listen_discard_event.is_set():
                                        try_enqueue(text)
                else:
                    if text and not self.listen_discard_event.is_set():
                        try_enqueue(text)
                time.sleep(0.1)
        except Exception as e:
            tb = traceback.format_exc()
            log_with_time(f"[FATAL] listen_loop异常: {e}\n{tb}")
            with open("fatal_error.log", "a", encoding="utf-8") as f:
                f.write(f"[FATAL] listen_loop异常: {e}\n{tb}\n")

    def _normalize_pinyin(self, text):
        py = lazy_pinyin(text)
        py = [re.sub(r'[12-5]', '', s) for s in py]
        py = [s.replace('eng', 'en').replace('ing', 'in').replace('ang', 'an').replace('ong', 'on') for s in py]
        py = [s.replace('h', 'f') if s.startswith(('h', 'f')) else s for s in py]
        return ''.join(py)

    def _start_autostop_timer(self):
        # 启动前先取消旧的倒计时
        if hasattr(self, '_countdown_timer') and self._countdown_timer:
            self._countdown_timer.cancel()
        if self.enable_autostop:
            if hasattr(self, 'autostop_timer') and self.autostop_timer:
                self.autostop_timer.cancel()
            self._countdown_time = self.autostop_time
            self._update_countdown_label()
            self._countdown_timer = threading.Timer(1, self._countdown_tick)
            self._countdown_timer.start()
            self.autostop_timer = threading.Timer(self.autostop_time, self._autostop_action)
            self.autostop_timer.start()

    def _countdown_tick(self):
        if hasattr(self, '_countdown_time') and self._countdown_time > 0:
            self._countdown_time -= 1
            self._update_countdown_label()
            if self._countdown_time > 0:
                self._countdown_timer = threading.Timer(1, self._countdown_tick)
                self._countdown_timer.start()
            else:
                self.label_countdown.setText("")

    def _update_countdown_label(self):
        if hasattr(self, '_countdown_time') and self._countdown_time > 0:
            self.label_countdown.setText(f"({self._countdown_time}s)")
        else:
            self.label_countdown.setText("")

    def _autostop_action(self):
        # 停止倒计时线程，清空label
        self.label_countdown.setText("")
        if hasattr(self, '_countdown_timer') and self._countdown_timer:
            self._countdown_timer.cancel()
        if self.enable_wakeword:
            self.voice_queue.queue.clear()
            self.processing = False
            self.wake_state = 'idle'
            self.append_text(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] [系统] 已自动退出唤醒，等待唤醒词")
            log_with_time("[系统] 已自动退出唤醒，等待唤醒词")
        else:
            self.stop_listen()

    def process_next(self):
        # 原逻辑存在竞态：多个调用在自处理线程设置processing=True之前并发进入，导致多线程处理和潜在崩溃
        with self.process_lock:
            if getattr(self, 'processing', False):
                log_with_time("[DEBUG] process_next: 已在processing中(加锁检查)，返回")
                return
            self.processing = True  # 先占位，防止并发
        def nowstr():
            return datetime.datetime.now().strftime("%H:%M:%S")
        def _process():
            try:
                log_with_time("[DEBUG] process_next: 进入processing主线程")
                logi("PROC_ENTER processing loop")
                while self.listening or not self.voice_queue.empty():
                    try:
                        if self.voice_queue.empty():
                            time.sleep(0.05)
                            continue
                        text = self.voice_queue.get()
                        snippet = (text[:200] + '...') if len(text) > 200 else text
                        log_with_time(f"[DEBUG] process_next: 取出队列文本(len={len(text)}): {snippet}")
                        logi(f"QUEUE_POP len={len(text)}")
                        if text and len(text.strip()) == 1:
                            log_with_time(f"[DEBUG] process_next: 1字噪音丢弃: {text}")
                            logi("QUEUE_DROP_1CHAR")
                            continue
                        self.update_queue_list()
                        msg_user = f"[{nowstr()}] [你] {text}"
                        self.append_text(msg_user)
                        log_with_time(f"[你] {text}")
                        msg_sys = f"[{nowstr()}] [系统] 正在加载模型与生成回复..."
                        self.append_text(msg_sys)
                        log_with_time("[系统] 正在加载模型与生成回复...")
                        logi("LLM_PREPARE")
                        self.listen_pause.set()
                        self.set_status_light(False)
                        if hasattr(self, '_countdown_timer') and self._countdown_timer:
                            try:
                                self._countdown_timer.cancel()
                            except Exception:
                                pass
                        if hasattr(self, 'autostop_timer') and self.autostop_timer:
                            try:
                                self.autostop_timer.cancel()
                            except Exception:
                                pass
                        try:
                            send_text = text + " /no_think" if getattr(self, 'no_think', False) else text
                            logi(f"LLM_REQ url={self.lmstudio_url} model={self.lmstudio_model} len={len(send_text)}")
                            t0 = time.time()
                            thinking, answer = query_lmstudio(send_text, self.lmstudio_url, self.lmstudio_model)
                            t1 = time.time()
                            logi(f"LLM_RESP dt={(t1-t0):.3f}s think_len={len(thinking) if thinking else 0} ans_len={len(answer) if answer else 0}")
                        except Exception as e:
                            log_with_time(f"[ERROR] query_lmstudio异常: {e}")
                            logx("LLM_EXCEPTION")
                            self.append_text(f"[{nowstr()}] [系统] AI回复异常: {e}")
                            answer = "抱歉，AI回复失败。"
                            thinking = None
                        if thinking:
                            # 只显示，不进TTS
                            msg_think = f"[{nowstr()}] [思考] {thinking}"
                            self.append_text(msg_think)
                            log_with_time(f"[思考] {thinking}")
                        if not answer:
                            # 若无回答，给出友好提示并跳过TTS
                            err_msg = f"[{nowstr()}] [系统] AI未返回有效回答（可能网络/服务异常）。"
                            self.append_text(err_msg)
                            log_with_time("[系统] AI未返回有效回答，已跳过TTS")
                            logw("LLM_EMPTY_ANSWER")
                            # 恢复状态并继续下一轮
                            self.listen_discard_event.clear()
                            continue
                        msg_ai = f"[{nowstr()}] [AI] {answer}"
                        self.append_text(msg_ai)
                        log_with_time(f"[AI] {answer}")
                        self.listen_discard_event.set()
                        self.set_status_light(False)
                        import json, traceback
                        try:
                            log_with_time(f"[DEBUG] process_next: TTS准备阶段 answer长度={len(answer)}")
                            logi(f"TTS_PREP ans_len={len(answer)}")
                            tts_text = answer
                            is_json_command = False
                            try:
                                parsed = json.loads(answer)
                                current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                enhanced_json = {"id": current_time, **parsed}
                                if "kaishidamo" in parsed and str(parsed["kaishidamo"]) == "1":
                                    with open("action_damo.txt", "w", encoding="utf-8") as f:
                                        f.write(json.dumps(enhanced_json, ensure_ascii=False, indent=2))
                                    tts_text = "开始打磨命令已收到"
                                    is_json_command = True
                                    log_with_time("[DEBUG] JSON包含kaishidamo=1 -> action_damo.txt 写入并播报: 开始打磨命令已收到")
                                    logi("JSON_OUT action_damo.txt (kaishidamo=1)")
                                elif "source" in parsed:
                                    with open("model_command.txt", "w", encoding="utf-8") as f:
                                        f.write(json.dumps(enhanced_json, ensure_ascii=False, indent=2))
                                    tts_text = "产品入库命令已收到"
                                    is_json_command = True
                                    log_with_time("[DEBUG] JSON包含source -> model_command.txt 写入并播报: 产品入库命令已收到")
                                    logi("JSON_OUT model_command.txt (source present)")
                                else:
                                    with open("model_command.txt", "w", encoding="utf-8") as f:
                                        f.write(json.dumps(enhanced_json, ensure_ascii=False, indent=2))
                                    tts_text = "命令已收到"
                                    is_json_command = True
                                    log_with_time("[DEBUG] JSON无kaishidamo/source -> 使用通用播报: 命令已收到")
                                    logi("JSON_OUT model_command.txt (generic)")
                            except Exception:
                                pass
                            self._enqueue_tts(tts_text, priority=is_json_command)
                            log_with_time(f"[DEBUG] process_next: 已入队TTS priority={is_json_command}")
                            logi(f"TTS_ENQUEUED priority={is_json_command} len={len(tts_text)}")
                        except Exception as e:
                            log_with_time(f"[ERROR] TTS阶段异常: {e}\n{traceback.format_exc()}")
                            logx("TTS_PREP_EXCEPTION")
                            self.append_text(f"[{nowstr()}] [系统] TTS阶段异常: {e}")
                        finally:
                            self.listen_discard_event.clear()
                            log_with_time("[DEBUG] process_next: 本轮处理结束")
                            logi("PROC_ITER_END")
                    except Exception as loop_e:
                        import traceback
                        log_with_time(f"[ERROR] process_next内部循环异常: {loop_e}\n{traceback.format_exc()}")
                        logx("PROC_LOOP_EXCEPTION")
                log_with_time("[DEBUG] process_next: 处理循环退出 (listening=%s queue_empty=%s)" % (self.listening, self.voice_queue.empty()))
                logi(f"PROC_EXIT listening={self.listening} queue_empty={self.voice_queue.empty()}")
            except Exception as e:
                import traceback
                log_with_time(f"[ERROR] process_next主异常: {e}\n{traceback.format_exc()}")
                logx("PROC_MAIN_EXCEPTION")
            finally:
                with self.process_lock:
                    self.processing = False
                log_with_time("[DEBUG] process_next: processing标志已清除")
                logi("PROC_FLAG_CLEARED")
        threading.Thread(target=_process, daemon=True).start()

    def update_queue_list(self):
        self.list_queue.clear()
        for t, text in self.voice_history:
            self.list_queue.addItem(f"[{t}] {text}")
    
    def init_action_damo_file(self):
        """初始化action_damo.txt文件"""
        action_file_path = "action_damo.txt"
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            if not os.path.exists(action_file_path):
                # 文件不存在，创建新文件
                initial_data = {
                    "kaishidamo": "0",
                    "id": current_time
                }
                with open(action_file_path, "w", encoding="utf-8") as f:
                    json.dump(initial_data, f, ensure_ascii=False, indent=2)
                log_with_time(f"创建action_damo.txt文件: {initial_data}")
            else:
                # 文件存在，读取并重置kaishidamo为0
                with open(action_file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                # 重置kaishidamo字段为0
                data["kaishidamo"] = "0"
                data["id"] = current_time  # 更新时间戳
                
                with open(action_file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                log_with_time(f"重置action_damo.txt文件kaishidamo为0: {data}")
                
        except Exception as e:
            log_with_time(f"初始化action_damo.txt文件失败: {str(e)}")

# SettingsDialog保留为设置对话框
class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.layout = QtWidgets.QFormLayout()

        # 基础配置控件
        self.lmstudio_url_edit = QtWidgets.QLineEdit()
        self.lmstudio_model_edit = QtWidgets.QLineEdit()
        self.vosk_model_path_edit = QtWidgets.QLineEdit()

        # 新增：可独立启用/停用 MQTT 与 SQLite
        self.enable_mqtt_checkbox = QtWidgets.QCheckBox("启用 MQTT（进程间消息）")
        self.enable_sqlite_checkbox = QtWidgets.QCheckBox("启用 SQLite（本地任务队列）")

        # 其他配置
        self.enable_wakeword_checkbox = QtWidgets.QCheckBox("启用唤醒词识别")
        self.wakeword_edit = QtWidgets.QLineEdit()
        self.wakeword_edit.setPlaceholderText("如：你好小明")
        self.block_wakeword_after_wake_checkbox = QtWidgets.QCheckBox("唤醒后屏蔽唤醒词（对话期间不再检测唤醒词）")
        self.enable_autostop_checkbox = QtWidgets.QCheckBox("启用定时自动停止")
        self.autostop_time_edit = QtWidgets.QLineEdit()
        self.autostop_time_edit.setPlaceholderText("秒数，如30")
        self.no_think_checkbox = QtWidgets.QCheckBox("No Think（向模型追加 /no_think）")
        self.tts_delay_mode_combo = QtWidgets.QComboBox()
        self.tts_delay_mode_combo.addItems(["动态计算", "固定延迟(秒)"])
        self.tts_fixed_delay_edit = QtWidgets.QLineEdit()
        self.tts_fixed_delay_edit.setPlaceholderText("固定延迟秒，默认3")

        # 加载与渲染
        self.load_config()
        self.sync_config_to_ui()

    def save_config(self):
        mode = 'dynamic' if self.tts_delay_mode_combo.currentIndex() == 0 else 'fixed'
        config = {
            "lmstudio_url": self.lmstudio_url_edit.text(),
            "lmstudio_model": self.lmstudio_model_edit.text(),
            "vosk_model_path": self.vosk_model_path_edit.text(),
            "enable_mqtt": self.enable_mqtt_checkbox.isChecked(),
            "enable_sqlite": self.enable_sqlite_checkbox.isChecked(),
            "enable_wakeword": self.enable_wakeword_checkbox.isChecked(),
            "wakeword": self.wakeword_edit.text(),
            "block_wakeword_after_wake": self.block_wakeword_after_wake_checkbox.isChecked(),
            "enable_autostop": self.enable_autostop_checkbox.isChecked(),
            "autostop_time": self.autostop_time_edit.text(),
            "no_think": self.no_think_checkbox.isChecked(),
            "tts_delay_mode": mode,
            "tts_fixed_delay": self.tts_fixed_delay_edit.text() or '3'
        }
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    def sync_config_to_ui(self):
        config = SettingsDialog.read_config()
        self.lmstudio_url_edit.setText(config.get("lmstudio_url", "http://localhost:1234/v1/chat/completions"))
        self.lmstudio_model_edit.setText(config.get("lmstudio_model", "your-model-name"))
        self.vosk_model_path_edit.setText(config.get("vosk_model_path", "E:/AITools/model/Vosk/vosk-model-cn-0.22"))
        self.enable_mqtt_checkbox.setChecked(config.get("enable_mqtt", True))
        self.enable_sqlite_checkbox.setChecked(config.get("enable_sqlite", True))
        self.enable_wakeword_checkbox.setChecked(config.get("enable_wakeword", False))
        self.wakeword_edit.setText(config.get("wakeword", "你好小明"))
        self.block_wakeword_after_wake_checkbox.setChecked(config.get("block_wakeword_after_wake", True))
        self.enable_autostop_checkbox.setChecked(config.get("enable_autostop", False))
        self.autostop_time_edit.setText(str(config.get("autostop_time", 30)))
        self.no_think_checkbox.setChecked(config.get("no_think", False))
        mode = config.get("tts_delay_mode", "fixed")
        self.tts_delay_mode_combo.setCurrentIndex(0 if mode == 'dynamic' else 1)
        self.tts_fixed_delay_edit.setText(str(config.get("tts_fixed_delay", 3)))

        # 表单构建
        self.layout.addRow("LMStudio地址:", self.lmstudio_url_edit)
        self.layout.addRow("LMStudio模型名:", self.lmstudio_model_edit)
        self.layout.addRow("Vosk模型路径:", self.vosk_model_path_edit)
        self.layout.addRow(self.enable_mqtt_checkbox)
        self.layout.addRow(self.enable_sqlite_checkbox)
        self.layout.addRow(self.enable_wakeword_checkbox)
        self.layout.addRow("唤醒词:", self.wakeword_edit)
        self.layout.addRow(self.block_wakeword_after_wake_checkbox)
        self.layout.addRow(self.enable_autostop_checkbox)
        self.layout.addRow("定时自动停止(秒):", self.autostop_time_edit)
        self.layout.addRow(self.no_think_checkbox)
        self.layout.addRow("TTS延迟模式:", self.tts_delay_mode_combo)
        self.layout.addRow("固定延迟(秒):", self.tts_fixed_delay_edit)
        btn_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        self.layout.addWidget(btn_box)
        self.setLayout(self.layout)

    def load_config(self):
        config = SettingsDialog.read_config()
        self.lmstudio_url_edit.setText(config.get("lmstudio_url", "http://localhost:1234/v1/chat/completions"))
        self.lmstudio_model_edit.setText(config.get("lmstudio_model", "your-model-name"))
        self.vosk_model_path_edit.setText(config.get("vosk_model_path", "E:/AITools/model/Vosk/vosk-model-cn-0.22"))
        self.enable_mqtt_checkbox.setChecked(config.get("enable_mqtt", True))
        self.enable_sqlite_checkbox.setChecked(config.get("enable_sqlite", True))
        self.enable_wakeword_checkbox.setChecked(config.get("enable_wakeword", False))
        self.wakeword_edit.setText(config.get("wakeword", "你好小明"))
        self.block_wakeword_after_wake_checkbox.setChecked(config.get("block_wakeword_after_wake", True))
        self.enable_autostop_checkbox.setChecked(config.get("enable_autostop", False))
        self.autostop_time_edit.setText(str(config.get("autostop_time", 30)))
        self.no_think_checkbox.setChecked(config.get("no_think", False))
        # 延迟模式在sync中处理

    @staticmethod
    def read_config():
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


def run_app():
    import sys
    import traceback
    def excepthook(type, value, tb):
        msg = f"[FATAL] 未捕获异常: {value}\n{''.join(traceback.format_exception(type, value, tb))}"
        print(msg)
        try:
            with open("fatal_error.log", "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass
    sys.excepthook = excepthook
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())

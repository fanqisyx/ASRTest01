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
    def __init__(self):
        super().__init__()
        log_with_time(f"[TTS] MainWindow.__init__: self id={id(self)}")
        # 强制使用队列连接确保跨线程信号正常工作
        from PyQt5.QtCore import Qt
        connection_result = self.tts_signal.connect(self._tts_on_main_thread, Qt.QueuedConnection)
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
        # 测试信号槽连接
        self.test_signal_connection()

    def _safe_speak(self, text):
        """安全的TTS播报方法，用于唤醒回复等简短文本"""
        try:
            log_with_time(f"[TTS] _safe_speak: 播报: {text}")
            import subprocess
            
            # 转义文本
            escaped_text = text.replace('"', '""')
            
            # 使用修复后的PowerShell命令
            ps_cmd = f'''Add-Type -AssemblyName System.Speech; $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; $synth.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::NotSet, [System.Speech.Synthesis.VoiceAge]::NotSet, 0, [System.Globalization.CultureInfo]::CreateSpecificCulture("zh-CN")); $synth.Speak("{escaped_text}"); $synth.Dispose()'''
            
            result = subprocess.run(
                ["powershell", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            if result.returncode == 0:
                log_with_time(f"[TTS] _safe_speak: 播报完成: {text}")
            else:
                # 备选：使用系统提示音
                import winsound
                winsound.MessageBeep(winsound.MB_ICONINFORMATION)
                log_with_time(f"[TTS] _safe_speak: 使用提示音替代: {text}")
                
        except Exception as e:
            log_with_time(f"[TTS] _safe_speak: 播报异常: {e}")
    
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
            # 写入增强后的JSON
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
            # 估算TTS朗读时长，rate=200字/分钟（pyttsx3默认），加0.3秒缓冲
            char_count = len(text)
            log_with_time(f"[TTS] _tts_on_main_thread: 字符数={char_count}")
            chars_per_second = 200 / 60
            estimated = char_count / chars_per_second + 0.3
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
                self.set_status_light(True)
                text = vosk_module.recognize_speech(self.vosk_model_path, stop_event=self.listen_stop_event, discard_event=self.listen_discard_event)
                if not self.listening:
                    break
                nowstr = datetime.datetime.now().strftime('%H:%M:%S')
                # 只收到1个字时，视为噪音，丢弃
                if text and len(text.strip()) == 1:
                    continue
                if text:
                    self.voice_history.append((nowstr, text))
                    self.update_queue_list()
                if self.enable_wakeword:
                    if self.wake_state == 'idle':
                        if text:
                            text_pinyin = self._normalize_pinyin(text)
                            if wakeword_pinyin and wakeword_pinyin in text_pinyin:
                                self.wake_state = 'waked'
                                self.append_text(f"[{nowstr}] [系统] 检测到唤醒词，已唤醒")
                                log_with_time("[系统] 检测到唤醒词，已唤醒")
                                self._start_autostop_timer()  # 唤醒后立即启动倒计时
                                self.listen_discard_event.set()
                                self.set_status_light(False)
                                # 使用安全的系统TTS播报唤醒回复
                                self._safe_speak("你好！")
                                self.listen_discard_event.clear()
                                if self.listening:
                                    self.set_status_light(True)
                                if not self.block_wakeword_after_wake:
                                    if not self.processing and self.voice_queue.empty():
                                        self.voice_queue.put(text)
                                        self.process_next()
                    elif self.wake_state == 'waked':
                        if self.block_wakeword_after_wake:
                            if text and not self.listen_discard_event.is_set():
                                # 无论processing状态如何都推送，保证多轮对话
                                self.voice_queue.put(text)
                                self.process_next()
                        else:
                            if text:
                                text_pinyin = self._normalize_pinyin(text)
                                if wakeword_pinyin and wakeword_pinyin in text_pinyin:
                                    self.append_text(f"[{nowstr}] [系统] 检测到唤醒词，已唤醒")
                                    log_with_time("[系统] 检测到唤醒词，已唤醒")
                                    self.listen_discard_event.set()
                                    self.set_status_light(False)
                                    # 使用安全的系统TTS播报唤醒回复
                                    self._safe_speak("你好！")
                                    self.listen_discard_event.clear()
                                    if self.listening:
                                        self.set_status_light(True)
                                else:
                                    if text and not self.listen_discard_event.is_set():
                                        if not self.processing and self.voice_queue.empty():
                                            self.voice_queue.put(text)
                                            self.process_next()
                else:
                    if text and not self.listen_discard_event.is_set():
                        if not self.processing and self.voice_queue.empty():
                            self.voice_queue.put(text)
                            self.process_next()
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
        if self.processing:
            log_with_time("[DEBUG] process_next: 已在processing中，直接返回")
            return
        def nowstr():
            return datetime.datetime.now().strftime("%H:%M:%S")
        def _process():
            with self.process_lock:
                self.processing = True
                log_with_time("[DEBUG] process_next: 进入processing流程")
                try:
                    while self.listening or not self.voice_queue.empty():
                        if not self.voice_queue.empty():
                            text = self.voice_queue.get()
                            log_with_time(f"[DEBUG] process_next: 取出队列文本: {text}")
                            # 只收到1个字时，视为噪音，丢弃
                            if text and len(text.strip()) == 1:
                                log_with_time(f"[DEBUG] process_next: 1字噪音丢弃: {text}")
                                continue
                            self.update_queue_list()
                            msg_user = f"[{nowstr()}] [你] {text}"
                            self.append_text(msg_user)
                            log_with_time(f"[你] {text}")
                            msg_sys = f"[{nowstr()}] [系统] 正在加载模型与生成回复..."
                            self.append_text(msg_sys)
                            log_with_time("[系统] 正在加载模型与生成回复...")
                            self.listen_pause.set()
                            self.set_status_light(False)
                            # 对话期间停止倒计时（cancel），TTS播报后再重启
                            if hasattr(self, '_countdown_timer') and self._countdown_timer:
                                log_with_time("[DEBUG] process_next: 取消倒计时计时器，防止TTS期间退出唤醒")
                                self._countdown_timer.cancel()
                            if hasattr(self, 'autostop_timer') and self.autostop_timer:
                                log_with_time("[DEBUG] process_next: 取消主自动停止计时器，防止TTS期间退出唤醒")
                                self.autostop_timer.cancel()
                            try:
                                thinking, answer = query_lmstudio(text, self.lmstudio_url, self.lmstudio_model)
                            except Exception as e:
                                log_with_time(f"[ERROR] query_lmstudio异常: {e}")
                                self.append_text(f"[{nowstr()}] [系统] AI回复异常: {e}")
                                answer = "抱歉，AI回复失败。"
                                thinking = None
                            if thinking:
                                msg_think = f"[{nowstr()}] [思考] {thinking}"
                                self.append_text(msg_think)
                                log_with_time(f"[思考] {thinking}")
                            msg_ai = f"[{nowstr()}] [AI] {answer}"
                            self.append_text(msg_ai)
                            log_with_time(f"[AI] {answer}")
                            self.listen_discard_event.set()
                            self.set_status_light(False)
                            import threading, traceback, sys
                            import json
                            try:
                                log_with_time(f"[DEBUG] process_next: TTS播报前参数: answer={answer}, tts_stop_event={self.tts_stop_event.is_set()}")
                                log_with_time(f"[DEBUG] process_next: 开始TTS播报 (主线程: {threading.main_thread().ident}, 当前线程: {threading.current_thread().ident})")
                                import os
                                with open("fatal_error.log", "a", encoding="utf-8") as f:
                                    f.write(f"[DEBUG] process_next: TTS播报前参数: answer={answer}, tts_stop_event={self.tts_stop_event.is_set()}\n")
                                    f.write(f"[DEBUG] process_next: 开始TTS播报 (主线程: {threading.main_thread().ident}, 当前线程: {threading.current_thread().ident})\n")
                                # 新增：如为JSON，写入txt并只播报“命令已收到”
                                tts_text = answer
                                try:
                                    parsed = json.loads(answer)
                                    # 为JSON添加时间ID
                                    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    enhanced_json = {
                                        "id": current_time,
                                        **parsed  # 将原始JSON内容合并
                                    }
                                    # 写入增强后的JSON
                                    enhanced_json_str = json.dumps(enhanced_json, ensure_ascii=False, indent=2)
                                    with open("model_command.txt", "w", encoding="utf-8") as f:
                                        f.write(enhanced_json_str)
                                    tts_text = "命令已收到"
                                    log_with_time(f"[DEBUG] process_next: answer为JSON，已添加时间ID({current_time})并写入model_command.txt，仅播报命令已收到")
                                except Exception:
                                    pass
                                # 用Qt信号让TTS在主线程执行
                                log_with_time(f"[DEBUG] process_next: emit前 self id={id(self)}")
                                log_with_time(f"[DEBUG] process_next: signal类型={type(self.tts_signal)}")
                                log_with_time(f"[DEBUG] process_next: 当前线程是否为主线程={threading.current_thread() == threading.main_thread()}")
                                
                                # 放弃Qt信号机制，直接在工作线程中调用TTS（使用线程安全方式）
                                log_with_time(f"[DEBUG] process_next: Qt信号失效，改用直接调用方式")
                                log_with_time(f"[DEBUG] process_next: 直接调用TTS函数")
                                
                                # 直接调用TTS函数（使用系统TTS，更稳定）
                                import threading
                                def safe_tts_call():
                                    try:
                                        log_with_time(f"[TTS] safe_tts_call: 开始TTS播报, text={tts_text}")
                                        log_with_time("[TTS] safe_tts_call: 设置listen_pause，暂停收音")
                                        self.listen_pause.set()
                                        log_with_time("[TTS] safe_tts_call: 使用系统TTS播报")
                                        
                                        # 使用Windows系统SAPI语音引擎，避免pyttsx3崩溃问题
                                        import time
                                        import subprocess
                                        try:
                                            # 方法1：使用PowerShell的SAPI语音合成
                                            log_with_time("[TTS] safe_tts_call: 使用PowerShell SAPI TTS")
                                            # 转义文本中的特殊字符
                                            escaped_text = tts_text.replace('"', '""').replace("'", "''")
                                            ps_cmd = f'''Add-Type -AssemblyName System.Speech; $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; $synth.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::NotSet, [System.Speech.Synthesis.VoiceAge]::NotSet, 0, [System.Globalization.CultureInfo]::CreateSpecificCulture("zh-CN")); $synth.Speak("{escaped_text}"); $synth.Dispose()'''
                                            
                                            log_with_time(f"[TTS] safe_tts_call: 执行PowerShell命令播报: {tts_text}")
                                            result = subprocess.run(
                                                ["powershell", "-Command", ps_cmd],
                                                capture_output=True,
                                                text=True,
                                                timeout=30,  # 30秒超时
                                                creationflags=subprocess.CREATE_NO_WINDOW  # 不显示PowerShell窗口
                                            )
                                            
                                            if result.returncode == 0:
                                                log_with_time("[TTS] safe_tts_call: PowerShell TTS播放完成")
                                            else:
                                                raise Exception(f"PowerShell TTS失败: {result.stderr}")
                                                
                                        except Exception as tts_e:
                                            log_with_time(f"[TTS] safe_tts_call: PowerShell TTS异常: {tts_e}")
                                            # 方法2：fallback到简单的系统提示音
                                            try:
                                                log_with_time("[TTS] safe_tts_call: 使用系统提示音作为备选")
                                                import winsound
                                                # 播放系统提示音表示有消息
                                                winsound.MessageBeep(winsound.MB_ICONINFORMATION)
                                                log_with_time(f"[TTS] safe_tts_call: 系统提示音播放完成，内容: {tts_text}")
                                            except Exception as beep_e:
                                                log_with_time(f"[TTS] safe_tts_call: 系统提示音也失败: {beep_e}")
                                        
                                        log_with_time("[TTS] safe_tts_call: TTS处理完成，准备估算延迟")
                                        # 估算TTS朗读时长，rate=200字/分钟（中文语音），加0.5秒缓冲
                                        char_count = len(tts_text)
                                        log_with_time(f"[TTS] safe_tts_call: 字符数={char_count}")
                                        chars_per_second = 200 / 60  # 每秒约3.33个字符
                                        estimated = char_count / chars_per_second + 0.5
                                        log_with_time(f"[TTS] safe_tts_call: 延迟{estimated:.2f}秒后恢复收音")
                                        time.sleep(estimated)
                                        log_with_time("[TTS] safe_tts_call: 延迟结束，准备恢复收音")
                                        self.listen_pause.clear()
                                        log_with_time("[TTS] safe_tts_call: 已恢复收音")
                                        # 确保状态指示灯正确更新
                                        if self.listening:
                                            log_with_time("[TTS] safe_tts_call: 尝试更新状态指示灯")
                                    except Exception as e:
                                        import traceback
                                        tb = traceback.format_exc()
                                        log_with_time(f"[TTS] safe_tts_call: 异常: {e}\n{tb}")
                                        # 异常时也要恢复收音
                                        self.listen_pause.clear()
                                
                                # 在当前线程中直接调用（避免创建新线程）
                                safe_tts_call()
                                log_with_time("[DEBUG] process_next: TTS直接调用完成")
                            except Exception as e:
                                tb = traceback.format_exc()
                                log_with_time(f"[ERROR] TTS播报异常: {e}\n{tb}")
                                with open("fatal_error.log", "a", encoding="utf-8") as f:
                                    f.write(f"[ERROR] TTS播报异常: {e}\n{tb}\n")
                                self.append_text(f"[{nowstr()}] [系统] TTS播报异常: {e}")
                            self.listen_discard_event.clear()
                            # TTS已由safe_tts_call完全处理，包括收音恢复
                            log_with_time("[DEBUG] process_next: TTS处理完成，状态已由TTS函数管理")
                            # TTS播报后重启倒计时
                            try:
                                log_with_time("[DEBUG] process_next: TTS播报后重启倒计时")
                                self._start_autostop_timer()
                            except Exception as e:
                                log_with_time(f"[ERROR] 倒计时重启异常: {e}")
                        else:
                            time.sleep(0.1)
                except Exception as e:
                    log_with_time(f"[ERROR] process_next主循环异常: {e}")
                finally:
                    self.processing = False
                    log_with_time("[DEBUG] process_next: 退出processing流程")
        threading.Thread(target=_process, daemon=True).start()

    def update_queue_list(self):
        self.list_queue.clear()
        for t, text in self.voice_history:
            self.list_queue.addItem(f"[{t}] {text}")

# SettingsDialog保留为设置对话框
class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.layout = QtWidgets.QFormLayout()
        self.lmstudio_url_edit = QtWidgets.QLineEdit()
        self.lmstudio_model_edit = QtWidgets.QLineEdit()
        self.vosk_model_path_edit = QtWidgets.QLineEdit()
        self.enable_wakeword_checkbox = QtWidgets.QCheckBox("启用唤醒词识别")
        self.wakeword_edit = QtWidgets.QLineEdit()
        self.wakeword_edit.setPlaceholderText("如：你好小明")
        self.block_wakeword_after_wake_checkbox = QtWidgets.QCheckBox("唤醒后屏蔽唤醒词（对话期间不再检测唤醒词）")
        self.enable_autostop_checkbox = QtWidgets.QCheckBox("启用定时自动停止")
        self.autostop_time_edit = QtWidgets.QLineEdit()
        self.autostop_time_edit.setPlaceholderText("秒数，如30")
        self.load_config()
        self.sync_config_to_ui()

    def save_config(self):
        config = {
            "lmstudio_url": self.lmstudio_url_edit.text(),
            "lmstudio_model": self.lmstudio_model_edit.text(),
            "vosk_model_path": self.vosk_model_path_edit.text(),
            "enable_wakeword": self.enable_wakeword_checkbox.isChecked(),
            "wakeword": self.wakeword_edit.text(),
            "block_wakeword_after_wake": self.block_wakeword_after_wake_checkbox.isChecked(),
            "enable_autostop": self.enable_autostop_checkbox.isChecked(),
            "autostop_time": self.autostop_time_edit.text()
        }
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    def sync_config_to_ui(self):
        config = SettingsDialog.read_config()
        self.lmstudio_url_edit.setText(config.get("lmstudio_url", "http://localhost:1234/v1/chat/completions"))
        self.lmstudio_model_edit.setText(config.get("lmstudio_model", "your-model-name"))
        self.vosk_model_path_edit.setText(config.get("vosk_model_path", "E:/AITools/model/Vosk/vosk-model-cn-0.22"))
        self.enable_wakeword_checkbox.setChecked(config.get("enable_wakeword", False))
        self.wakeword_edit.setText(config.get("wakeword", "你好小明"))
        self.block_wakeword_after_wake_checkbox.setChecked(config.get("block_wakeword_after_wake", True))
        self.enable_autostop_checkbox.setChecked(config.get("enable_autostop", False))
        self.autostop_time_edit.setText(str(config.get("autostop_time", 30)))
        self.layout.addRow("LMStudio地址:", self.lmstudio_url_edit)
        self.layout.addRow("LMStudio模型名:", self.lmstudio_model_edit)
        self.layout.addRow("Vosk模型路径:", self.vosk_model_path_edit)
        self.layout.addRow(self.enable_wakeword_checkbox)
        self.layout.addRow("唤醒词:", self.wakeword_edit)
        self.layout.addRow(self.block_wakeword_after_wake_checkbox)
        self.layout.addRow(self.enable_autostop_checkbox)
        self.layout.addRow("定时自动停止(秒):", self.autostop_time_edit)
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
        self.enable_wakeword_checkbox.setChecked(config.get("enable_wakeword", False))
        self.wakeword_edit.setText(config.get("wakeword", "你好小明"))
        self.block_wakeword_after_wake_checkbox.setChecked(config.get("block_wakeword_after_wake", True))
        self.enable_autostop_checkbox.setChecked(config.get("enable_autostop", False))
        self.autostop_time_edit.setText(str(config.get("autostop_time", 30)))

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

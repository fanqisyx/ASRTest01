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
from tts_module import speak_text
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

# MainWindow主界面类，包含所有主流程和UI逻辑
class MainWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("语音助手整合Demo")
        self.voice_queue = queue.Queue()
        self.voice_history = []
        self.listening = False
        self.processing = False
        self.listen_pause = threading.Event()
        self.listen_stop_event = threading.Event()
        self.listen_discard_event = threading.Event()
        self.tts_stop_event = threading.Event()
        self.process_lock = threading.Lock()
        self.autostop_timer = None
        self.init_ui()
        self.load_config()

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
        if self.listening:
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

    def stop_listen(self):
        self.listening = False
        self.processing = False
        self.tts_stop_event.set()
        self.set_status_light(False)
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.wake_state = 'idle'
        # 停止倒计时线程，清空label
        self.label_countdown.setText("")
        if hasattr(self, '_countdown_timer') and self._countdown_timer:
            self._countdown_timer.cancel()
        msg = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] [系统] 已停止聆听。"
        self.append_text(msg)
        log_with_time(msg)

    def listen_loop(self):
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
                            speak_text_interruptable("你好！", self.tts_stop_event)
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
                                speak_text_interruptable("你好！", self.tts_stop_event)
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
                            try:
                                log_with_time(f"[DEBUG] process_next: 开始TTS播报 (主线程: {threading.main_thread().ident}, 当前线程: {threading.current_thread().ident})")
                                speak_text_interruptable(answer, self.tts_stop_event)
                                log_with_time(f"[DEBUG] process_next: TTS播报结束 (主线程: {threading.main_thread().ident}, 当前线程: {threading.current_thread().ident})")
                            except Exception as e:
                                tb = traceback.format_exc()
                                log_with_time(f"[ERROR] TTS播报异常: {e}\n{tb}")
                                self.append_text(f"[{nowstr()}] [系统] TTS播报异常: {e}")
                            self.listen_discard_event.clear()
                            self.listen_pause.clear()
                            if self.listening:
                                self.set_status_light(True)
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

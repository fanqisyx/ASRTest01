import sys
import json
import threading
import sqlite3
import os
import time
from PyQt5 import QtWidgets, QtCore

from shared.config_helper import read_config
from shared.db import init_db, clear_events
from main import listen_loop
from vosk_module import get_vosk_model


class ASRWindow(QtWidgets.QWidget):
    # 跨线程信号：日志与唤醒状态
    log_signal = QtCore.pyqtSignal(str)
    wake_signal = QtCore.pyqtSignal(bool)
    def __init__(self):
        super().__init__()
        self.setWindowTitle('ASR 应用')
        self.resize(720, 480)

        form = QtWidgets.QFormLayout(self)

        # 简要入口参数
        self.model_path = QtWidgets.QLineEdit()
        self.db_path = QtWidgets.QLineEdit()
        self.enable_mqtt = QtWidgets.QCheckBox('启用 MQTT')
        self.enable_sqlite = QtWidgets.QCheckBox('启用 SQLite')

        cfg = read_config()
        self.model_path.setText(cfg.get('vosk_model_path', ''))
        self.db_path.setText(cfg.get('db_path', 'asr_app.db'))
        self.enable_mqtt.setChecked(bool(cfg.get('enable_mqtt', True)))
        self.enable_sqlite.setChecked(bool(cfg.get('enable_sqlite', True)))

        form.addRow('Vosk模型路径:', self.model_path)
        form.addRow('数据库文件:', self.db_path)
        form.addRow(self.enable_mqtt)
        form.addRow(self.enable_sqlite)

        # 操作按钮与指示灯
        btns = QtWidgets.QHBoxLayout()
        self.indicator = QtWidgets.QLabel()
        self.indicator.setFixedSize(16, 16)
        self.indicator.setToolTip('收音指示灯：绿=正在收音，灰=被本地文件禁止收音，黑=未开启收音')
        self._indicator_state = None  # 'black' | 'gray' | 'green'
        # 唤醒指示灯
        self.wake_indicator = QtWidgets.QLabel()
        self.wake_indicator.setFixedSize(16, 16)
        self.wake_indicator.setToolTip('唤醒指示灯：绿=已唤醒，黑=未唤醒')
        self._wake_indicator_state = None  # 'black' | 'green'
        self._awake_state = False
        self.btn_save = QtWidgets.QPushButton('保存配置')
        self.btn_settings = QtWidgets.QPushButton('设置')
        self.btn_run = QtWidgets.QPushButton('开始收音')
        btns.addWidget(QtWidgets.QLabel('收音:'))
        btns.addWidget(self.indicator)
        btns.addSpacing(8)
        btns.addWidget(QtWidgets.QLabel('唤醒:'))
        btns.addWidget(self.wake_indicator)
        btns.addStretch(1)
        btns.addWidget(self.btn_save)
        btns.addWidget(self.btn_settings)
        btns.addWidget(self.btn_run)
        form.addRow(btns)

        self.btn_save.clicked.connect(lambda: self.save_cfg(show_message=True))
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_run.clicked.connect(self.toggle_listen)

        # 日志框
        self.log_view = QtWidgets.QTextEdit()
        self.log_view.setReadOnly(True)
        form.addRow('日志:', self.log_view)

        # 连接跨线程信号到 UI 控件
        self.log_signal.connect(self.log_view.append)
        self.wake_signal.connect(self._on_wake_state)

        # 启动即清空数据库内容（等价于清除第一行）
        try:
            init_db()
            clear_events()
        except Exception:
            pass

        # 状态字段
        self._listen_thread = None
        self._stop_event = None
        self._last_event_id = 0

        # 软件打开时：界面先显示，再在后台加载模型，避免界面卡住
        self._model_thread = None
        self._logged_model_start = False
        self._logged_model_done = False
        QtCore.QTimer.singleShot(0, self._maybe_bg_load_model)

        # UI定时器：刷新指示灯与拉取日志
        self._ui_timer = QtCore.QTimer(self)
        self._ui_timer.setInterval(500)
        self._ui_timer.timeout.connect(self._on_tick)
        self._ui_timer.start()

        # 自动开始收音
        auto_start = bool(cfg.get('auto_start_listen', False))
        if auto_start:
            QtCore.QTimer.singleShot(200, self.toggle_listen)

    def _maybe_bg_load_model(self):
        path = self.model_path.text().strip()
        if not path:
            return
        def _run():
            try:
                get_vosk_model(path)
            except Exception:
                pass
        self._model_thread = threading.Thread(target=_run, daemon=True)
        self._model_thread.start()
        # 重置模型加载日志标记
        self._logged_model_start = False
        self._logged_model_done = False

    def _set_indicator(self, color: str):
        if color == self._indicator_state:
            return
        self._indicator_state = color
        css_map = {
            'black': 'background-color: #000000; border-radius: 8px;',
            'gray': 'background-color: #9e9e9e; border-radius: 8px;',
            'green': 'background-color: #00c853; border-radius: 8px;',
        }
        self.indicator.setStyleSheet(css_map.get(color, css_map['black']))

    def _set_wake_indicator(self, color: str):
        if color == self._wake_indicator_state:
            return
        self._wake_indicator_state = color
        css_map = {
            'black': 'background-color: #000000; border-radius: 8px;',
            'green': 'background-color: #00c853; border-radius: 8px;',
        }
        self.wake_indicator.setStyleSheet(css_map.get(color, css_map['black']))

    def _on_tick(self):
        # 指示灯：根据是否在收音 + mic_guard 文件
        listening = bool(self._listen_thread and self._listen_thread.is_alive())
        if not listening:
            self._set_indicator('black')
            # 未在收音时，唤醒态也应视为无效
            if self._awake_state:
                self._awake_state = False
            self._set_wake_indicator('black')
        else:
            # 如果模型仍在加载，视为未真正开始收音，不显示为绿色
            if self._model_thread is not None and self._model_thread.is_alive():
                self._set_indicator('black')
                # 模型加载时不显示唤醒
                self._set_wake_indicator('black')
            else:
                guard_val = None
                try:
                    cfg = read_config()
                    guard_file = cfg.get('mic_guard_file', 'mic_guard.txt')
                    if guard_file and os.path.exists(guard_file):
                        with open(guard_file, 'r', encoding='utf-8', errors='ignore') as f:
                            guard_val = f.read().strip()
                except Exception:
                    guard_val = None
                if guard_val == '1':
                    self._set_indicator('green')
                else:
                    self._set_indicator('gray')

        # 模型加载状态日志
        if self._model_thread is not None:
            if not self._logged_model_start:
                self.log_view.append('正在后台加载 Vosk 模型…')
                self._logged_model_start = True
            if not self._model_thread.is_alive() and not self._logged_model_done:
                self.log_view.append('模型加载完成（或已结束）。')
                self._logged_model_done = True

        # 拉取数据库中的新事件并显示
        self._fetch_new_events()

    def _on_wake_state(self, awakened: bool):
        self._awake_state = bool(awakened)
        self._set_wake_indicator('green' if awakened else 'black')

    def _fetch_new_events(self):
        # 解析数据库路径：相对路径与写入端保持一致，落在 ASR_App 目录
        raw = self.db_path.text().strip() or 'asr_app.db'
        if os.path.isabs(raw):
            db_path = raw
        else:
            app_dir = os.path.dirname(os.path.abspath(__file__))
            db_path = os.path.abspath(os.path.join(app_dir, raw))
        if not os.path.exists(db_path):
            return
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute(
                'SELECT id, time, command, parameter FROM events WHERE id > ? ORDER BY id ASC LIMIT 50',
                (self._last_event_id,)
            )
            rows = cur.fetchall()
            conn.close()
        except Exception:
            return
        if not rows:
            return
        for ev_id, ev_time, command, param in rows:
            try:
                pdata = json.loads(param) if param else {}
            except Exception:
                pdata = {}
            if command == 'listened':
                line = f"[{ev_time}] 识别：{pdata.get('listened', '')}"
                # 若此前处于唤醒态，这一条识别后退出唤醒
                if self._awake_state:
                    self._awake_state = False
                    self._set_wake_indicator('black')
            else:
                line = f"[{ev_time}] {command}：{param}"
            self.log_view.append(line)
            self._last_event_id = ev_id
    def save_cfg(self, show_message: bool = False):
        cfg = read_config()
        cfg.update({
            'vosk_model_path': self.model_path.text().strip(),
            'db_path': self.db_path.text().strip() or 'asr_app.db',
            'enable_mqtt': self.enable_mqtt.isChecked(),
            'enable_sqlite': self.enable_sqlite.isChecked(),
        })
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        if show_message:
            QtWidgets.QMessageBox.information(self, '保存成功', '配置已保存')
        # 统一写到日志
        self.log_view.append('配置已保存。')

    def open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            dlg.save_config()
            # 同步关键字段到主界面
            cfg = read_config()
            self.model_path.setText(cfg.get('vosk_model_path', ''))
            self.db_path.setText(cfg.get('db_path', 'asr_app.db'))
            self.enable_mqtt.setChecked(bool(cfg.get('enable_mqtt', True)))
            self.enable_sqlite.setChecked(bool(cfg.get('enable_sqlite', True)))

    def toggle_listen(self):
        # 停止
        if self._listen_thread and self._listen_thread.is_alive():
            if self._stop_event:
                self._stop_event.set()
            self._listen_thread.join(timeout=1.5)
            self._listen_thread = None
            self._stop_event = None
            self.btn_run.setText('开始收音')
            self.log_view.append('停止收音。')
            return

        # 开始：先保存当前配置，确保收音线程与日志读取使用同一个配置/数据库路径
        self.save_cfg(show_message=False)
        init_db()
        # 启动收音前清空（只保留空表）
        try:
            clear_events()
        except Exception:
            pass
        self._stop_event = threading.Event()
        self._listen_thread = threading.Thread(
            target=listen_loop,
            args=(self._stop_event,),
            kwargs={'on_event': self._on_asr_event},
            daemon=True,
        )
        self._listen_thread.start()
        self.btn_run.setText('停止收音')
        self.log_view.append('开始收音。')

    # 供 ASR 线程回调（非 UI 线程）：通过信号更新 UI
    def _on_asr_event(self, kind: str, payload: dict | None = None):
        payload = payload or {}
        if kind == 'heard':
            ts = time.strftime('%H:%M:%S', time.localtime())
            text = payload.get('text', '')
            self.log_signal.emit(f'[{ts}] 听到：{text}')
        elif kind == 'wake':
            self.wake_signal.emit(True)
        elif kind == 'listened':
            # 显示识别结果，并熄灭唤醒灯
            ts = time.strftime('%H:%M:%S', time.localtime())
            text = payload.get('text', '')
            self.log_signal.emit(f'[{ts}] 识别：{text}')
            self.wake_signal.emit(False)


class SettingsDialog(QtWidgets.QDialog):
    """ASR 设置（去除 LMStudio 相关）"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('设置')
        form = QtWidgets.QFormLayout(self)

        # 基础与通用
        self.vosk_model_path_edit = QtWidgets.QLineEdit()
        self.db_path_edit = QtWidgets.QLineEdit()
        self.enable_mqtt_checkbox = QtWidgets.QCheckBox('启用 MQTT（进程间消息）')
        self.enable_sqlite_checkbox = QtWidgets.QCheckBox('启用 SQLite（本地任务队列）')
        self.auto_start_listen_checkbox = QtWidgets.QCheckBox('软件打开后自动开始收音')

        # 识别体验
        self.enable_wakeword_checkbox = QtWidgets.QCheckBox('启用唤醒词识别')
        self.wakeword_edit = QtWidgets.QLineEdit()
        self.wakeword_edit.setPlaceholderText('如：你好小明')
        # 提示音路径
        self.wake_beep_path_edit = QtWidgets.QLineEdit()
        self.wake_beep_path_edit.setPlaceholderText('唤醒提示音 WAV 路径，如 C:/sounds/wake.wav')
        self.wake_beep_browse_btn = QtWidgets.QPushButton('选择…')
        self.wake_beep_browse_btn.clicked.connect(self._browse_wake_beep)
        self.block_wakeword_after_wake_checkbox = QtWidgets.QCheckBox('唤醒后屏蔽唤醒词（对话期间不再检测唤醒词）')
        self.enable_autostop_checkbox = QtWidgets.QCheckBox('启用定时自动停止')
        self.autostop_time_edit = QtWidgets.QLineEdit()
        self.autostop_time_edit.setPlaceholderText('秒数，如30')

        # 语音屏蔽文件与轮询
        self.mic_guard_file_edit = QtWidgets.QLineEdit()
        self.mic_guard_file_edit.setPlaceholderText('收音开关文件路径，如 mic_guard.txt，内容为1时可收音')
        self.mic_guard_interval_edit = QtWidgets.QLineEdit()
        self.mic_guard_interval_edit.setPlaceholderText('轮询间隔(秒)，默认0.5')

        # 读入配置
        cfg = read_config()
        self.vosk_model_path_edit.setText(cfg.get('vosk_model_path', ''))
        self.db_path_edit.setText(cfg.get('db_path', 'asr_app.db'))
        self.enable_mqtt_checkbox.setChecked(bool(cfg.get('enable_mqtt', True)))
        self.enable_sqlite_checkbox.setChecked(bool(cfg.get('enable_sqlite', True)))
        self.auto_start_listen_checkbox.setChecked(bool(cfg.get('auto_start_listen', False)))
        self.enable_wakeword_checkbox.setChecked(bool(cfg.get('enable_wakeword', False)))
        self.wakeword_edit.setText(cfg.get('wakeword', '你好小明'))
        self.wake_beep_path_edit.setText(cfg.get('wake_beep_path', ''))
        self.block_wakeword_after_wake_checkbox.setChecked(bool(cfg.get('block_wakeword_after_wake', True)))
        self.enable_autostop_checkbox.setChecked(bool(cfg.get('enable_autostop', False)))
        self.autostop_time_edit.setText(str(cfg.get('autostop_time', 30)))
        self.mic_guard_file_edit.setText(cfg.get('mic_guard_file', 'mic_guard.txt'))
        self.mic_guard_interval_edit.setText(str(cfg.get('mic_guard_interval', 0.5)))

        # 表单
        form.addRow('Vosk模型路径:', self.vosk_model_path_edit)
        form.addRow('数据库文件:', self.db_path_edit)
        form.addRow(self.enable_mqtt_checkbox)
        form.addRow(self.enable_sqlite_checkbox)
        form.addRow(self.auto_start_listen_checkbox)
        form.addRow(self.enable_wakeword_checkbox)
        form.addRow('唤醒词:', self.wakeword_edit)
        # 将“路径输入+选择按钮”放到一行
        _beep_row_widget = QtWidgets.QWidget()
        _beep_row_layout = QtWidgets.QHBoxLayout(_beep_row_widget)
        _beep_row_layout.setContentsMargins(0, 0, 0, 0)
        _beep_row_layout.addWidget(self.wake_beep_path_edit, 1)
        _beep_row_layout.addWidget(self.wake_beep_browse_btn, 0)
        form.addRow('唤醒提示音(WAV):', _beep_row_widget)

        # 其余表单项
        form.addRow(self.block_wakeword_after_wake_checkbox)
        form.addRow(self.enable_autostop_checkbox)
        form.addRow('定时自动停止(秒):', self.autostop_time_edit)
        form.addRow('收音开关文件:', self.mic_guard_file_edit)
        form.addRow('收音轮询间隔(秒):', self.mic_guard_interval_edit)

        btn_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        form.addRow(btn_box)

    def _browse_wake_beep(self):
        # 解析当前文本，去掉可能的引号，作为初始目录
        cur = (self.wake_beep_path_edit.text() or '').strip().strip('"').strip("'").strip('“').strip('”')
        start_dir = os.path.dirname(cur) if cur and os.path.exists(os.path.dirname(cur)) else os.path.expanduser('~')
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            '选择唤醒提示音 WAV 文件',
            start_dir,
            'WAV 文件 (*.wav);;所有文件 (*)'
        )
        if file_path:
            self.wake_beep_path_edit.setText(file_path)

    def save_config(self):
        cfg = read_config()
        cfg.update({
            'vosk_model_path': self.vosk_model_path_edit.text().strip(),
            'db_path': self.db_path_edit.text().strip() or 'asr_app.db',
            'enable_mqtt': self.enable_mqtt_checkbox.isChecked(),
            'enable_sqlite': self.enable_sqlite_checkbox.isChecked(),
            'auto_start_listen': self.auto_start_listen_checkbox.isChecked(),
            'enable_wakeword': self.enable_wakeword_checkbox.isChecked(),
            'wakeword': self.wakeword_edit.text().strip(),
            'wake_beep_path': self.wake_beep_path_edit.text().strip(),
            'block_wakeword_after_wake': self.block_wakeword_after_wake_checkbox.isChecked(),
            'enable_autostop': self.enable_autostop_checkbox.isChecked(),
            'autostop_time': int(self.autostop_time_edit.text().strip() or '30'),
            'mic_guard_file': self.mic_guard_file_edit.text().strip() or 'mic_guard.txt',
            'mic_guard_interval': float(self.mic_guard_interval_edit.text().strip() or '0.5'),
        })
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)


def run():
    app = QtWidgets.QApplication(sys.argv)
    w = ASRWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    run()

import sys
import json
import threading
from PyQt5 import QtWidgets, QtCore

from shared.config_helper import read_config
from main import LlmWorker


class LLMWindow(QtWidgets.QWidget):
    # 来自工作线程的事件信号 (event_name, data)
    event_sig = QtCore.pyqtSignal(str, dict)

    def __init__(self):
            super().__init__()
            self.setWindowTitle('LLM 应用')
            self.resize(700, 520)

            layout = QtWidgets.QFormLayout(self)

            # 控件
            self.api = QtWidgets.QLineEdit()
            self.model = QtWidgets.QLineEdit()
            self.db_path = QtWidgets.QLineEdit()  # 兼容旧字段
            self.system_prompt_path = QtWidgets.QLineEdit()
            self.asr_db_path = QtWidgets.QLineEdit()
            self.llm_db_path = QtWidgets.QLineEdit()
            self.poll_interval = QtWidgets.QDoubleSpinBox()
            self.poll_interval.setDecimals(2)
            self.poll_interval.setRange(0.05, 10.0)
            self.poll_interval.setSingleStep(0.05)
            self.enable_mqtt = QtWidgets.QCheckBox('启用 MQTT')
            self.enable_sqlite = QtWidgets.QCheckBox('启用 SQLite')
            self.no_think = QtWidgets.QCheckBox('附加 /no_think')
            self.autostart = QtWidgets.QCheckBox('启动自动运行')
            # 状态与日志
            self.last_listened = QtWidgets.QLineEdit(); self.last_listened.setReadOnly(True)
            self.last_reply = QtWidgets.QLineEdit(); self.last_reply.setReadOnly(True)
            self.log = QtWidgets.QPlainTextEdit(); self.log.setReadOnly(True)

            # 载入配置
            cfg = read_config()
            self.api.setText(cfg.get('lmstudio_url', 'http://localhost:1234/v1/chat/completions'))
            self.model.setText(cfg.get('lmstudio_model', 'your-model-name'))
            self.db_path.setText(cfg.get('db_path', 'llm_app.db'))
            self.system_prompt_path.setText(cfg.get('system_prompt_path', ''))
            self.asr_db_path.setText(cfg.get('asr_db_path', cfg.get('db_path', 'asr_app.db')))
            self.llm_db_path.setText(cfg.get('llm_db_path', cfg.get('db_path', 'llm_app.db')))
            self.poll_interval.setValue(float(cfg.get('asr_poll_interval', 0.5)))
            self.enable_mqtt.setChecked(bool(cfg.get('enable_mqtt', True)))
            self.enable_sqlite.setChecked(bool(cfg.get('enable_sqlite', True)))
            self.no_think.setChecked(bool(cfg.get('no_think', False)))
            self.autostart.setChecked(bool(cfg.get('autostart', False)))

            # 布局
            layout.addRow('LMStudio地址:', self.api)
            layout.addRow('模型名:', self.model)
            layout.addRow('数据库文件(旧):', self.db_path)
            layout.addRow('系统提示词TXT:', self._with_pick(self.system_prompt_path, '选择TXT', filter='TXT 文件 (*.txt)'))
            layout.addRow('ASR 数据库:', self._with_pick(self.asr_db_path, '选择DB', filter='SQLite (*.db);;所有文件 (*.*)'))
            layout.addRow('LLM 数据库:', self._with_pick(self.llm_db_path, '选择DB', filter='SQLite (*.db);;所有文件 (*.*)'))
            layout.addRow('ASR 轮询间隔(s):', self.poll_interval)
            layout.addRow(self.enable_mqtt)
            layout.addRow(self.enable_sqlite)
            layout.addRow(self.no_think)
            layout.addRow(self.autostart)
            layout.addRow('最近听到:', self.last_listened)
            layout.addRow('最近回复:', self.last_reply)
            layout.addRow('运行日志:', self.log)

            btns = QtWidgets.QHBoxLayout()
            self.btn_save = QtWidgets.QPushButton('保存配置')
            self.btn_run = QtWidgets.QPushButton('开始运行')
            self.btn_stop = QtWidgets.QPushButton('停止运行')
            self.btn_stop.setEnabled(False)
            btns.addWidget(self.btn_save)
            btns.addWidget(self.btn_run)
            btns.addWidget(self.btn_stop)
            layout.addRow(btns)

            # 事件
            self.btn_save.clicked.connect(self.save_cfg)
            self.btn_run.clicked.connect(self.run_llm)
            self.btn_stop.clicked.connect(self.stop_llm)
            self.event_sig.connect(self._on_event_ui)

            # 运行期 worker 引用
            self.worker = None
            self._thread = None

    def _with_pick(self, line_edit: QtWidgets.QLineEdit, btn_text: str, filter: str = '所有文件 (*.*)'):
        box = QtWidgets.QHBoxLayout(); w = QtWidgets.QWidget(); w.setLayout(box)
        box.addWidget(line_edit)
        btn = QtWidgets.QPushButton(btn_text); box.addWidget(btn)
        def pick():
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, '选择文件', '', filter)
            if path: line_edit.setText(path)
        btn.clicked.connect(pick)
        return w

    def save_cfg(self):
        cfg = read_config()
        cfg.update({
            'lmstudio_url': self.api.text().strip(),
            'lmstudio_model': self.model.text().strip(),
            'db_path': self.db_path.text().strip() or 'llm_app.db',
            'system_prompt_path': self.system_prompt_path.text().strip(),
            'asr_db_path': self.asr_db_path.text().strip(),
            'llm_db_path': self.llm_db_path.text().strip(),
            'asr_poll_interval': float(self.poll_interval.value()),
            'enable_mqtt': self.enable_mqtt.isChecked(),
            'enable_sqlite': self.enable_sqlite.isChecked(),
            'no_think': self.no_think.isChecked(),
            'autostart': self.autostart.isChecked(),
        })
        with open('config.json','w',encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        if self.worker:
            try:
                self.worker.poll_interval = float(cfg.get('asr_poll_interval', 0.5))
                # 热更新 no_think 开关
                self.worker.no_think = bool(cfg.get('no_think', False))
                if hasattr(self.worker, '_normalize_path'):
                    self.worker.system_prompt_path = self.worker._normalize_path(cfg.get('system_prompt_path'))
                else:
                    self.worker.system_prompt_path = cfg.get('system_prompt_path')
            except Exception:
                pass
        QtWidgets.QMessageBox.information(self, '保存成功', '配置已保存（路径更改已自动生效）')

    def run_llm(self):
        # 避免重复启动
        if self._thread and self._thread.is_alive():
            # 不弹窗，写入日志
            try:
                self._append_log('[SYS] 已在运行')
            except Exception:
                pass
            return
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.worker = LlmWorker()
        self.worker.on_event = lambda ev, data: self.event_sig.emit(ev, data)
        self._thread = threading.Thread(target=self.worker.loop, daemon=True)
        self._thread.start()
        # 不弹窗，写入日志
        try:
            self._append_log('[SYS] 已启动后台运行')
        except Exception:
            pass

    def stop_llm(self):
        # 安全停止后台线程与 MQTT
        try:
            if not self._thread or not self._thread.is_alive():
                return
            if self.worker:
                self.worker.stop = True
                try:
                    if getattr(self.worker, 'client', None):
                        # 停止 MQTT 循环并断开
                        try:
                            self.worker.client.loop_stop()
                        except Exception:
                            pass
                        try:
                            self.worker.client.disconnect()
                        except Exception:
                            pass
                except Exception:
                    pass
            # 等待线程退出
            self._thread.join(timeout=5.0)
        finally:
            self.btn_run.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self._append_log('[SYS] 已停止运行')
            self.worker = None
            self._thread = None
            
    def showEvent(self, event):
        super().showEvent(event)
        # 打开窗口后根据配置自动运行
        try:
            if self.autostart.isChecked():
                self.run_llm()
        except Exception:
            pass

    def _on_event_ui(self, event: str, data: dict):
        try:
            if event == 'listened':
                text = data.get('text', '')
                self.last_listened.setText(text)
                self._append_log(f"[ASR] listened: {text}")
            elif event == 'replied':
                cmd = data.get('command', '')
                param = data.get('parameter', '')
                short_param = param if len(str(param)) <= 200 else (str(param)[:200] + '...')
                self.last_reply.setText(f"{cmd} | {short_param}")
                self._append_log(f"[LLM] reply: command={cmd}, parameter={short_param}")
        except Exception:
            pass

    def _append_log(self, line: str):
        ts = QtCore.QDateTime.currentDateTime().toString('yyyy-MM-dd HH:mm:ss')
        self.log.appendPlainText(f"{ts}  {line}")


def run():
    app = QtWidgets.QApplication(sys.argv)
    w = LLMWindow()
    w.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    run()

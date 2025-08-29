import sys
import json
import threading
from PyQt5 import QtWidgets, QtCore

from shared.config_helper import read_config
from shared.db import init_db
from main import TtsWorker


class TTSWindow(QtWidgets.QWidget):
    # 预留给工作线程的事件信号（可选）
    event_sig = QtCore.pyqtSignal(str, dict)

    def __init__(self):
        super().__init__()
        self.setWindowTitle('TTS 应用')
        self.resize(560, 320)
        layout = QtWidgets.QFormLayout(self)

        # 控件
        self.db_path = QtWidgets.QLineEdit()
        self.llm_db_path = QtWidgets.QLineEdit()
        self.enable_mqtt = QtWidgets.QCheckBox('启用 MQTT')
        self.enable_sqlite = QtWidgets.QCheckBox('启用 SQLite（旧任务队列）')
        self.autostart = QtWidgets.QCheckBox('启动自动运行')

        # 加载配置
        cfg = read_config()
        self.db_path.setText(cfg.get('db_path', 'tts_app.db'))
        self.llm_db_path.setText(cfg.get('llm_db_path', ''))
        self.enable_mqtt.setChecked(bool(cfg.get('enable_mqtt', True)))
        self.enable_sqlite.setChecked(bool(cfg.get('enable_sqlite', True)))
        self.autostart.setChecked(bool(cfg.get('autostart', False)))

        # 布局
        layout.addRow('TTS 自身数据库:', self.db_path)
        layout.addRow('LLM 数据库:', self._with_pick(self.llm_db_path, '选择DB', filter='SQLite (*.db);;所有文件 (*.*)'))
        layout.addRow(self.enable_mqtt)
        layout.addRow(self.enable_sqlite)
        layout.addRow(self.autostart)

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
        self.btn_run.clicked.connect(self.run_tts)
        self.btn_stop.clicked.connect(self.stop_tts)

        # 运行期引用
        self.worker = None
        self._thread = None

    def _with_pick(self, line_edit: QtWidgets.QLineEdit, btn_text: str, filter: str = '所有文件 (*.*)'):
        box = QtWidgets.QHBoxLayout()
        w = QtWidgets.QWidget()
        w.setLayout(box)
        box.addWidget(line_edit)
        btn = QtWidgets.QPushButton(btn_text)
        box.addWidget(btn)
        def pick():
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, '选择文件', '', filter)
            if path:
                line_edit.setText(path)
        btn.clicked.connect(pick)
        return w

    def save_cfg(self):
        cfg = read_config()
        cfg.update({
            'db_path': self.db_path.text().strip() or 'tts_app.db',
            'llm_db_path': self.llm_db_path.text().strip(),
            'enable_mqtt': self.enable_mqtt.isChecked(),
            'enable_sqlite': self.enable_sqlite.isChecked(),
            'autostart': self.autostart.isChecked(),
        })
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        QtWidgets.QMessageBox.information(self, '保存成功', '配置已保存')

    def run_tts(self):
        init_db()
        # 避免重复启动
        if self._thread and self._thread.is_alive():
            # 静默处理，不弹窗
            return
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.worker = TtsWorker()
        self._thread = threading.Thread(target=self.worker.loop, daemon=True)
        self._thread.start()
        # 静默处理，不弹窗

    def stop_tts(self):
        try:
            if not self._thread or not self._thread.is_alive():
                return
            if self.worker:
                self.worker.stop_flag = True
                try:
                    # 停止说话并关闭 MQTT
                    from tts_module import stop_tts as _stop
                    _stop()
                except Exception:
                    pass
                try:
                    if getattr(self.worker, 'client', None):
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
            self._thread.join(timeout=5.0)
        finally:
            self.btn_run.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.worker = None
            self._thread = None

    def showEvent(self, event):
        super().showEvent(event)
        # 打开窗口后根据配置自动运行
        try:
            if self.autostart.isChecked():
                self.run_tts()
        except Exception:
            pass


def run():
    app = QtWidgets.QApplication(sys.argv)
    w = TTSWindow()
    w.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    run()

import sys
import json
import threading
from PyQt5 import QtWidgets

from shared.config_helper import read_config
from shared.db import init_db
from main import TtsWorker


class TTSWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('TTS 应用')
        self.resize(480, 260)
        layout = QtWidgets.QFormLayout(self)

        self.db_path = QtWidgets.QLineEdit()
        self.enable_mqtt = QtWidgets.QCheckBox('启用 MQTT')
        self.enable_sqlite = QtWidgets.QCheckBox('启用 SQLite')

        cfg = read_config()
        self.db_path.setText(cfg.get('db_path','tts_app.db'))
        self.enable_mqtt.setChecked(bool(cfg.get('enable_mqtt', True)))
        self.enable_sqlite.setChecked(bool(cfg.get('enable_sqlite', True)))

        layout.addRow('数据库文件:', self.db_path)
        layout.addRow(self.enable_mqtt)
        layout.addRow(self.enable_sqlite)

        btns = QtWidgets.QHBoxLayout()
        self.btn_save = QtWidgets.QPushButton('保存配置')
        self.btn_run = QtWidgets.QPushButton('开始运行')
        btns.addWidget(self.btn_save)
        btns.addWidget(self.btn_run)
        layout.addRow(btns)

        self.btn_save.clicked.connect(self.save_cfg)
        self.btn_run.clicked.connect(self.run_tts)

    def save_cfg(self):
        cfg = read_config()
        cfg.update({
            'db_path': self.db_path.text().strip() or 'tts_app.db',
            'enable_mqtt': self.enable_mqtt.isChecked(),
            'enable_sqlite': self.enable_sqlite.isChecked(),
        })
        with open('config.json','w',encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        QtWidgets.QMessageBox.information(self, '保存成功', '配置已保存')

    def run_tts(self):
        init_db()
        self.btn_run.setEnabled(False)
        self.worker = TtsWorker()
        self._thread = threading.Thread(target=self.worker.loop, daemon=True)
        self._thread.start()
        QtWidgets.QMessageBox.information(self, '已启动', 'TTS 主循环已在后台运行')


def run():
    app = QtWidgets.QApplication(sys.argv)
    w = TTSWindow()
    w.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    run()

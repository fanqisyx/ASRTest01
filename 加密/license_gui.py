import sys
import os
import json
from PyQt5 import QtWidgets
from license_gen import generate_license
from license_gen import generate_keypair
from license_check import check_license
from machine_id import get_machine_id

class LicenseApp(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('License生成与校验工具')
        self.resize(400, 300)
        layout = QtWidgets.QVBoxLayout()


        # 本机机器码显示和复制
        machine_id = get_machine_id()
        machine_id_layout = QtWidgets.QHBoxLayout()
        self.machine_id_edit = QtWidgets.QLineEdit(machine_id)
        self.machine_id_edit.setReadOnly(True)
        self.btn_copy_machine_id = QtWidgets.QPushButton('复制')
        self.btn_copy_machine_id.clicked.connect(self.copy_machine_id)
        machine_id_layout.addWidget(QtWidgets.QLabel('本机机器码:'))
        machine_id_layout.addWidget(self.machine_id_edit)
        machine_id_layout.addWidget(self.btn_copy_machine_id)
        layout.addLayout(machine_id_layout)

        # 密钥对生成按钮
        self.btn_keypair = QtWidgets.QPushButton('生成密钥对(private.pem/public.pem)')
        self.btn_keypair.clicked.connect(self.on_keypair)
        layout.addWidget(self.btn_keypair)

        # 生成license部分
        group_gen = QtWidgets.QGroupBox('生成License')
        gen_layout = QtWidgets.QFormLayout()
        self.lic_type = QtWidgets.QComboBox()
        self.lic_type.addItems(['daily', 'permanent'])
        self.days_edit = QtWidgets.QLineEdit('1')
        self.gen_machine_id = QtWidgets.QLineEdit()
        self.gen_machine_id.setPlaceholderText('留空为本机，填写为其他设备机器码')
        gen_layout.addRow('类型:', self.lic_type)
        gen_layout.addRow('天数(仅日度):', self.days_edit)
        gen_layout.addRow('机器码:', self.gen_machine_id)
        self.btn_gen = QtWidgets.QPushButton('生成license.lic')
        self.btn_gen.clicked.connect(self.on_gen)
        gen_layout.addRow(self.btn_gen)
        group_gen.setLayout(gen_layout)
        layout.addWidget(group_gen)

        # 校验license部分
        group_chk = QtWidgets.QGroupBox('校验License')
        chk_layout = QtWidgets.QFormLayout()
        self.lic_path = QtWidgets.QLineEdit('license.lic')
        self.pub_path = QtWidgets.QLineEdit('public.pem')
        self.input_machine_id = QtWidgets.QLineEdit()
        self.input_machine_id.setPlaceholderText('留空为本机，填写为其他设备机器码')
        self.btn_chk = QtWidgets.QPushButton('校验')
        self.btn_chk.clicked.connect(self.on_chk)
        self.chk_result = QtWidgets.QLabel('')
        chk_layout.addRow('License路径:', self.lic_path)
        chk_layout.addRow('公钥路径:', self.pub_path)
        chk_layout.addRow('机器码:', self.input_machine_id)
        chk_layout.addRow(self.btn_chk)
        chk_layout.addRow('结果:', self.chk_result)
        group_chk.setLayout(chk_layout)
        layout.addWidget(group_chk)

        self.setLayout(layout)

    def copy_machine_id(self):
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(self.machine_id_edit.text())
        QtWidgets.QMessageBox.information(self, '提示', '本机机器码已复制到剪贴板！')

    def on_keypair(self):
        try:
            generate_keypair()
            QtWidgets.QMessageBox.information(self, '提示', '密钥对已生成！')
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, '错误', f'密钥生成失败: {e}')

    def on_gen(self):
        lic_type = self.lic_type.currentText()
        days = 1
        if lic_type == 'daily':
            try:
                days = int(self.days_edit.text())
            except Exception:
                days = 1
        custom_machine_id = self.gen_machine_id.text().strip()
        # monkey patch get_machine_id
        import machine_id as mid_mod
        orig_func = mid_mod.get_machine_id
        if custom_machine_id:
            mid_mod.get_machine_id = lambda: custom_machine_id
        generate_license(lic_type, days)
        mid_mod.get_machine_id = orig_func
        QtWidgets.QMessageBox.information(self, '提示', 'license.lic已生成')

    def on_chk(self):
        lic_path = self.lic_path.text()
        pub_path = self.pub_path.text()
        custom_machine_id = self.input_machine_id.text().strip()
        try:
            # monkey patch get_machine_id
            import machine_id as mid_mod
            orig_func = mid_mod.get_machine_id
            if custom_machine_id:
                mid_mod.get_machine_id = lambda: custom_machine_id
            result = check_license(lic_path, pub_path)
            mid_mod.get_machine_id = orig_func
            if isinstance(result, dict):
                self.chk_result.setText(result.get('msg', '未知结果'))
            else:
                self.chk_result.setText('授权有效' if result else '授权无效')
        except Exception as e:
            self.chk_result.setText(f'校验异常: {e}')

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    win = LicenseApp()
    win.show()
    sys.exit(app.exec_())

import uuid
import hashlib
import platform
import os

def get_machine_id():
    """
    获取本机唯一标识（仅与MAC地址和主板序列号相关）
    """
    # 取MAC地址
    mac = uuid.getnode()
    mac_str = f"{mac:012x}"
    # 取主板序列号（Windows）
    if platform.system() == 'Windows':
        try:
            import subprocess
            result = subprocess.check_output('wmic baseboard get serialnumber', shell=True)
            sn = result.decode(errors='ignore').split('\n')[1].strip()
        except Exception:
            sn = ''
    else:
        sn = ''
    raw = mac_str + sn
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()

if __name__ == '__main__':
    print('本机机器码:', get_machine_id())

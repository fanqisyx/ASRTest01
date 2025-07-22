
from machine_id import get_machine_id
from datetime import datetime, timedelta
import json
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256
import base64
import os

# 生成RSA密钥对（仅首次运行）
def generate_keypair():
    key = RSA.generate(2048)
    with open('private.pem', 'wb') as f:
        f.write(key.export_key())
    with open('public.pem', 'wb') as f:
        f.write(key.publickey().export_key())
    print('密钥对已生成')

# 生成license文件

def generate_license(license_type='daily', days=1):
    machine_id = get_machine_id()
    if license_type == 'permanent':
        expire = 'never'
    else:
        expire = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
    lic = {
        'machine_id': machine_id,
        'type': license_type,
        'expire': expire
    }
    lic_json = json.dumps(lic, sort_keys=True)
    # 签名
    with open('private.pem', 'rb') as f:
        priv = RSA.import_key(f.read())
    h = SHA256.new(lic_json.encode('utf-8'))
    signature = pkcs1_15.new(priv).sign(h)
    lic['signature'] = base64.b64encode(signature).decode()
    with open('license.lic', 'w', encoding='utf-8') as f:
        json.dump(lic, f, ensure_ascii=False, indent=2)
    print('license.lic已生成:', lic)

if __name__ == '__main__':
    import sys
    if not (os.path.exists('private.pem') and os.path.exists('public.pem')):
        generate_keypair()
    if len(sys.argv) > 1 and sys.argv[1] == 'permanent':
        generate_license('permanent')
    elif len(sys.argv) > 2 and sys.argv[1] == 'daily':
        generate_license('daily', int(sys.argv[2]))
    else:
        generate_license('daily', 1)

from machine_id import get_machine_id
import json
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256
import base64
from datetime import datetime

def check_license(license_path='license.lic', pubkey_path='public.pem'):
    with open(license_path, 'r', encoding='utf-8') as f:
        lic = json.load(f)
    machine_id = get_machine_id()
    if lic['machine_id'] != machine_id:
        return {'status': 'invalid', 'msg': '机器码不匹配，非法授权'}
    lic_json = json.dumps({k: lic[k] for k in ('machine_id','type','expire')}, sort_keys=True)
    with open(pubkey_path, 'rb') as f:
        pub = RSA.import_key(f.read())
    h = SHA256.new(lic_json.encode('utf-8'))
    try:
        pkcs1_15.new(pub).verify(h, base64.b64decode(lic['signature']))
    except (ValueError, TypeError):
        return {'status': 'invalid', 'msg': '签名校验失败'}
    if lic['type'] == 'permanent' or lic['expire'] == 'never':
        return {'status': 'permanent', 'msg': '永久授权，校验通过'}
    else:
        today = datetime.now().strftime('%Y-%m-%d')
        if today <= lic['expire']:
            return {'status': 'valid', 'msg': f'有效期内，校验通过（到期日: {lic["expire"]}）'}
        else:
            return {'status': 'expired', 'msg': f'授权已过期（到期日: {lic["expire"]}）'}

if __name__ == '__main__':
    check_license()

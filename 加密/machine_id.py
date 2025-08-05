import uuid

def get_machine_id():
    """
    获取本机唯一标识（示例实现，实际可根据需求更换为硬件ID等）
    """
    return str(uuid.getnode())

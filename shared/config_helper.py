import json
import os
from typing import Any, Dict

CONFIG_PATH = os.path.abspath(os.path.join(os.getcwd(), 'config.json'))


def read_config() -> Dict[str, Any]:
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

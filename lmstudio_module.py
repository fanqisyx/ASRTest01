# LMStudio通信模块
import requests
import json

import re

def extract_think_and_answer(text):
    """
    提取<think>…</think>为思考，其余为正式回答。
    """
    think_match = re.search(r'<think>([\s\S]*?)</think>', text, re.IGNORECASE)
    if think_match:
        thinking = think_match.group(1).strip()
        answer = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.IGNORECASE).strip()
    else:
        thinking = ''
        answer = text.strip()
    return thinking, answer

def query_lmstudio(text, api_url, model_name=None):
    """
    向LMStudio的OpenAI兼容接口发送请求，返回(思考, 回答)。
    model_name: 可选，指定模型名。
    """
    if model_name is None:
        model_name = "your-model-name"  # 可在设置中配置
    payload = {
        "model": model_name,
        "messages": [
            {"role": "user", "content": text}
        ]
    }
    try:
        resp = requests.post(api_url, json=payload, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            choices = data.get("choices", [])
            if choices:
                raw = choices[0]["message"]["content"]
                thinking, answer = extract_think_and_answer(raw)
                return thinking, answer
            else:
                return "[错误] 未返回choices", ""
        else:
            return f"[错误] HTTP {resp.status_code}", ""
    except Exception as e:
        return f"[错误] {e}", ""

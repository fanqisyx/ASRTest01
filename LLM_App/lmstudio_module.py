# 独立副本：LLM 使用
import requests
import json
import time
import re
import os

DEFAULT_CONNECT_TIMEOUT = 3
DEFAULT_READ_TIMEOUT = 60
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF = 0.6


def load_system_prompt():
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        prompt_file = os.path.join(current_dir, "System_Prompt.txt")
        if os.path.exists(prompt_file):
            with open(prompt_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                return content
        else:
            return "你是一个智能助手，请根据用户输入提供帮助。"
    except Exception:
        return "你是一个智能助手，请根据用户输入提供帮助。"


SYSTEM_PROMPT = load_system_prompt()


def extract_think_and_answer(text):
    think_match = re.search(r'<think>([\s\S]*?)</think>', text, re.IGNORECASE)
    if think_match:
        thinking = think_match.group(1).strip()
        answer = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.IGNORECASE).strip()
    else:
        thinking = ''
        answer = text.strip()
    return thinking, answer


def query_lmstudio(text, api_url, model_name=None,
                   retries: int = DEFAULT_RETRIES,
                   connect_timeout: int = DEFAULT_CONNECT_TIMEOUT,
                   read_timeout: int = DEFAULT_READ_TIMEOUT,
                   backoff_base: float = DEFAULT_BACKOFF,
                   system_prompt: str | None = None):
    if model_name is None:
        model_name = "your-model-name"
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": (system_prompt if isinstance(system_prompt, str) and system_prompt.strip() else SYSTEM_PROMPT)},
            {"role": "user", "content": text}
        ]
    }
    session = requests.Session()
    session.trust_env = False
    timeout = (connect_timeout, read_timeout)
    last_err_msg = None
    for attempt in range(retries + 1):
        try:
            resp = session.post(api_url, json=payload, timeout=timeout,
                                 proxies={"http": None, "https": None})
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices")
                if not choices or not isinstance(choices, list):
                    return "[错误] 响应缺少choices", ""
                first = choices[0] or {}
                message = first.get("message") or {}
                raw = message.get("content")
                if not raw or not isinstance(raw, str):
                    return "[错误] 响应缺少message.content", ""
                thinking, answer = extract_think_and_answer(raw)
                return thinking, answer
            else:
                last_err_msg = f"HTTP {resp.status_code}"
                if attempt < retries and resp.status_code in (500, 502, 503, 504, 429):
                    time.sleep(backoff_base * (2 ** attempt))
                    continue
                return f"[错误] {last_err_msg}", ""
        except requests.Timeout as te:
            last_err_msg = f"超时: {te}"
        except requests.RequestException as rexc:
            last_err_msg = f"请求异常: {rexc}"
        except Exception as e:
            last_err_msg = f"未知异常: {e}"
        if attempt < retries:
            time.sleep(backoff_base * (2 ** attempt))
            continue
        return f"[错误] {last_err_msg}", ""

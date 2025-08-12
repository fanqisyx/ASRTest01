# LMStudio通信模块
import requests
import json
import time
import re

DEFAULT_CONNECT_TIMEOUT = 3  # 秒
DEFAULT_READ_TIMEOUT = 60    # 秒
DEFAULT_RETRIES = 2          # 失败后重试次数（总请求=1+重试次数）
DEFAULT_BACKOFF = 0.6        # 指数退避起始秒

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

def query_lmstudio(text, api_url, model_name=None,
                   retries: int = DEFAULT_RETRIES,
                   connect_timeout: int = DEFAULT_CONNECT_TIMEOUT,
                   read_timeout: int = DEFAULT_READ_TIMEOUT,
                   backoff_base: float = DEFAULT_BACKOFF):
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
    # 禁用环境代理，避免企业代理影响到本地回环
    session = requests.Session()
    session.trust_env = False
    timeout = (connect_timeout, read_timeout)
    last_err_msg = None
    for attempt in range(retries + 1):
        try:
            resp = session.post(api_url, json=payload, timeout=timeout,
                                 proxies={"http": None, "https": None})
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except Exception as je:
                    return "[错误] 返回内容非JSON: %s" % je, ""
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
                # 5xx 或 429 可重试
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
        # 异常重试（到达最后一次则返回错误）
        if attempt < retries:
            time.sleep(backoff_base * (2 ** attempt))
            continue
        return f"[错误] {last_err_msg}", ""

import threading
tts_lock = threading.Lock()
# TTS模块
import pyttsx3


def speak_text(text):
    """
    用TTS朗读文本，优先使用中文语音。
    """
    import traceback
    try:
        print(f"[TTS] 尝试获取tts_lock... text={text}")
        with tts_lock:
            print(f"[TTS] 已获得tts_lock，初始化pyttsx3...")
            engine = pyttsx3.init()
            print(f"[TTS] pyttsx3初始化完成，获取voices...")
            voices = engine.getProperty('voices')
            for voice in voices:
                print(f"[TTS] 检查voice: {voice.name}")
                if "chinese" in voice.name.lower() or "huihui" in voice.name.lower() or "lili" in voice.name.lower() or "ting-ting" in voice.name.lower():
                    engine.setProperty('voice', voice.id)
                    print(f"[TTS] 选中voice: {voice.name}")
                    break
            print(f"[TTS] 开始say: {text}")
            engine.say(text)
            print(f"[TTS] say完成，runAndWait...")
            engine.runAndWait()
            print(f"[TTS] runAndWait完成")
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[FATAL] speak_text异常: {e}\n{tb}")
        with open("fatal_error.log", "a", encoding="utf-8") as f:
            f.write(f"[FATAL] speak_text异常: {e}\n{tb}\n")

def speak_text_interruptable(text, stop_event):
    """
    用TTS朗读文本，支持stop_event.set()时中断。
    注意：pyttsx3本身不支持强制中断，只能通过分句朗读+轮询stop_event实现近似中断。
    """
    import traceback
    try:
        print(f"[TTS] 尝试获取tts_lock... text={text}")
        with tts_lock:
            print(f"[TTS] 已获得tts_lock，初始化pyttsx3...")
            engine = pyttsx3.init()
            print(f"[TTS] pyttsx3初始化完成，获取voices...")
            voices = engine.getProperty('voices')
            for voice in voices:
                print(f"[TTS] 检查voice: {voice.name}")
                if "chinese" in voice.name.lower() or "huihui" in voice.name.lower() or "lili" in voice.name.lower() or "ting-ting" in voice.name.lower():
                    engine.setProperty('voice', voice.id)
                    print(f"[TTS] 选中voice: {voice.name}")
                    break
            # 按标点分句朗读，朗读前检测stop_event
            import re
            print(f"[TTS] 分句... text={text}")
            sentences = re.split(r'(。|！|？|\.|!|\?)', text)
            # 合并分隔符
            chunks = []
            for i in range(0, len(sentences)-1, 2):
                chunks.append(sentences[i] + sentences[i+1])
            if len(sentences) % 2 == 1:
                chunks.append(sentences[-1])
            print(f"[TTS] 分句结果: {chunks}")
            for chunk in chunks:
                if stop_event.is_set():
                    print(f"[TTS] stop_event已设置，中断TTS")
                    break
                print(f"[TTS] 开始say: {chunk}")
                engine.say(chunk)
                print(f"[TTS] say完成，runAndWait...")
                engine.runAndWait()
                print(f"[TTS] runAndWait完成")
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[FATAL] speak_text_interruptable异常: {e}\n{tb}")
        with open("fatal_error.log", "a", encoding="utf-8") as f:
            f.write(f"[FATAL] speak_text_interruptable异常: {e}\n{tb}\n")
    engine.stop()

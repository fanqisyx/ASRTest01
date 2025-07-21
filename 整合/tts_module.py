# TTS模块
import pyttsx3


def speak_text(text):
    """
    用TTS朗读文本，优先使用中文语音。
    """
    engine = pyttsx3.init()
    voices = engine.getProperty('voices')
    for voice in voices:
        if "chinese" in voice.name.lower() or "huihui" in voice.name.lower() or "lili" in voice.name.lower() or "ting-ting" in voice.name.lower():
            engine.setProperty('voice', voice.id)
            break
    engine.say(text)
    engine.runAndWait()

def speak_text_interruptable(text, stop_event):
    """
    用TTS朗读文本，支持stop_event.set()时中断。
    注意：pyttsx3本身不支持强制中断，只能通过分句朗读+轮询stop_event实现近似中断。
    """
    engine = pyttsx3.init()
    voices = engine.getProperty('voices')
    for voice in voices:
        if "chinese" in voice.name.lower() or "huihui" in voice.name.lower() or "lili" in voice.name.lower() or "ting-ting" in voice.name.lower():
            engine.setProperty('voice', voice.id)
            break
    # 按标点分句朗读，朗读前检测stop_event
    import re
    sentences = re.split(r'(。|！|？|\.|!|\?)', text)
    # 合并分隔符
    chunks = []
    for i in range(0, len(sentences)-1, 2):
        chunks.append(sentences[i] + sentences[i+1])
    if len(sentences) % 2 == 1:
        chunks.append(sentences[-1])
    for chunk in chunks:
        if stop_event.is_set():
            break
        engine.say(chunk)
        engine.iterate = True
        engine.runAndWait()
    engine.stop()

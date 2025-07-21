
import sys
import pyttsx3

def text_to_speech_pyttsx3(text):
    engine = pyttsx3.init()
    # 尝试设置中文语音
    voices = engine.getProperty('voices')
    for voice in voices:
        # 在 Windows 上可能是 "Microsoft Huihui Desktop" 或 "Microsoft Lili Desktop"
        # 在 macOS 上可能是 "Ting-Ting" 或 "Li-Mu" (这些都是旧名字，新系统可能不同)
        # 你可能需要打印 voice.id 和 voice.name 来查看可用的中文语音
        if "chinese" in voice.name.lower() or "huihui" in voice.name.lower() or "lili" in voice.name.lower() or "ting-ting" in voice.name.lower():
            engine.setProperty('voice', voice.id)
            break
    else:
        print("警告：未找到中文语音包，将使用默认语音。")

    engine.say(text)
    engine.runAndWait()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
        text_to_speech_pyttsx3(text)
    else:
        print("请在命令行参数中输入要朗读的内容，例如：python TTStest.py 测试成功")
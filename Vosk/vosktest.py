from vosk import Model, KaldiRecognizer
import pyaudio

model = Model(r"E:\AITools\model\Vosk\vosk-model-cn-0.22")
rec = KaldiRecognizer(model, 16000)

stream = pyaudio.PyAudio().open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)
stream.start_stream()

while True:
    data = stream.read(1024, exception_on_overflow=False)
    if rec.AcceptWaveform(data):
        print(rec.Result())  # 输出JSON格式的识别结果
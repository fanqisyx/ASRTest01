# 语音助手整合Demo

## 项目简介
本项目为基于PyQt5的本地语音助手整合Demo，集成了Vosk语音识别、pyttsx3本地TTS、LMStudio大模型API对话，支持唤醒词、自动停止、拼音模糊比对、可视化界面与配置。

## 主要技术路线
- **界面**：PyQt5
- **语音识别**：Vosk + pyaudio
- **TTS语音合成**：pyttsx3（本地离线）
- **大模型对话**：LMStudio（本地API，支持多种大模型）
- **拼音比对**：pypinyin
- **多线程/队列**：Python threading + queue
- **配置与日志**：config.json + 控制台/文件日志

## 使用方法
1. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
2. 下载Vosk中文模型（推荐0.22）：
   - [Vosk Model 中文0.22下载](https://alphacephei.com/vosk/models)
   - 解压后，将路径填入设置界面或config.json的`vosk_model_path`。
3. 启动LMStudio（或其他兼容OpenAI API的本地大模型服务），设置API地址与模型名。
4. 运行主程序：
   ```bash
   python main.py
   ```
5. 在界面中可设置唤醒词、自动停止时间、模型路径等。
6. 点击“开始聆听”即可体验语音对话。

## 主要功能
- 唤醒词识别（拼音模糊匹配）
- 语音转文本、文本转语音
- 多轮对话队列，TTS与收音互斥
- 自动停止倒计时，TTS期间暂停倒计时
- 配置热加载，日志输出
- 可视化界面与状态指示

## 目录结构
- `ui_main.py`：主界面与主流程
- `vosk_module.py`：Vosk语音识别封装
- `tts_module.py`：TTS播报封装
- `lmstudio_module.py`：LMStudio API对接
- `config.py`/`config.json`：配置管理
- `requirements.txt`：依赖列表

## 注意事项
- 需本地安装Vosk模型和LMStudio大模型服务。
- pyttsx3为本地TTS，部分系统需安装SAPI5或espeak。
- 若遇到闪退或异常，请查看控制台和fatal_error.log日志。

## 相关资源
- Vosk模型下载：[https://alphacephei.com/vosk/models](https://alphacephei.com/vosk/models)
- LMStudio下载：[https://lmstudio.ai/](https://lmstudio.ai/)
- PyQt5文档：[https://doc.qt.io/qtforpython/](https://doc.qt.io/qtforpython/)

## 许可证
仅供学习与交流，禁止商用。

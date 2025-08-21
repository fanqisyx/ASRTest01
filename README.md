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

## 拆分为3个独立服务（ASR/LLM/TTS）
新增基于本地 SQLite + MQTT 的解耦式三进程架构，源码在 `services/` 与 `shared/`：

- `services/asr_service.py`：监听麦克风，使用 Vosk 识别一句语音，写入 SQLite，并发布到 MQTT 主题 `asr/text` 与 `llm/ask`。
- `services/llm_service.py`：订阅 `llm/ask` 或从 SQLite 领取 LLM 任务，调用 LMStudio 接口，写入回答，并发布 `llm/answer` 和 `tts/speak`。
- `services/tts_service.py`：订阅 `tts/speak` 或从 SQLite 领取 TTS 任务，调用本地 pyttsx3 播报。支持 `tts/control` 的 stop 控制。

共享模块：
- `shared/db.py`：SQLite 表结构与任务队列（messages/tasks）
- `shared/mqtt_bus.py`：MQTT 主题与发布/订阅封装（默认 localhost:1883）
- `shared/config_helper.py`：读取 `config.json`

运行前准备：
1) 安装 MQTT broker（如 Mosquitto），或将 `MQTT_BROKER` 环境变量指向可用地址。
2) `pip install -r requirements.txt`（新增依赖：`paho-mqtt`）。
3) 在 `config.json` 配置 `vosk_model_path`、`lmstudio_url`、`lmstudio_model`。

分别启动服务（可在不同终端中运行）：
- 语音识别：`python services/asr_service.py`
- 模型服务：`python services/llm_service.py`
- 语音播报：`python services/tts_service.py`

三服务可与原 GUI 并行存在；GUI 不再直接耦合 TTS/ASR/LLM 的具体实现时，可转而通过 MQTT/SQLite 交互。

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

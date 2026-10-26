# 许可证与第三方组件

AudioLab Studio 自身代码按 MIT 使用（见项目根目录，如未附带 LICENSE 可视为 MIT）。
工作台集成了以下第三方项目/模型，分发或商用前请逐项确认。

## 代码依赖

| 组件 | 用途 | 许可证 | 链接 |
|---|---|---|---|
| python-audio-separator | 分离模型加载/推理封装 | MIT | https://github.com/nomadkaraoke/python-audio-separator |
| Demucs（上游思路/架构） | 分离模型架构之一 | MIT | https://github.com/facebookresearch/demucs |
| ColorSplitter（timbre-v1 编码器/权重） | 音色嵌入 | MIT | https://github.com/KakaruHayate/ColorSplitter |
| Resemblyzer（编码器网络定义） | 音色/说话人编码器 | MIT | https://github.com/resemble-ai/Resemblyzer |
| Silero VAD | 人声活动检测 | MIT | https://github.com/snakers4/silero-vad |
| sherpa-onnx | SenseVoice ONNX 推理运行时 | Apache-2.0 | https://github.com/k2-fsa/sherpa-onnx |
| SenseVoiceSmall（ONNX） | 中/英/日/韩/粤语转写 | MIT（SenseVoice / FunASR） | https://github.com/FunAudioLLM/SenseVoice |
| AST（AudioSet Transformer） | 场景标签 | BSD-3-Clause | https://huggingface.co/MIT/ast-finetuned-audioset-10-10-0.4593 |
| librosa | 音频特征/重采样 | ISC | https://librosa.org |
| soundfile | WAV I/O | BSD-3-Clause | https://python-soundfile.readthedocs.io |
| ffmpeg | 编解码/滤镜 | LGPL/GPL（取决于构建） | https://ffmpeg.org |
| FastAPI / Uvicorn | 本地 API | MIT / BSD-3-Clause | https://fastapi.tiangolo.com |
| React / Vite / lucide-react | 工作台前端 | MIT / MIT / ISC | https://react.dev |
| pywebview / pythonnet | 桌面窗口 | BSD-3-Clause / MIT | https://pywebview.flowrl.com |

## 模型权重

模型权重**不随本仓库分发**，由 `models` 页面或 `scripts/fetch_models.py` 从上游/镜像下载：

| 权重 | 来源 | 说明 |
|---|---|---|
| `model_bs_roformer_ep_317_sdr_12.9755.ckpt` | `lainlives/audio-separator-models`（Hugging Face 镜像） | UVR 社区模型；上游 `beveradb` 仓库当前不可匿名访问 |
| `UVR-MDX-NET-Inst_HQ_4.onnx` | 同上 | 59MB 兜底模型 |
| `timbre-v1.pt` | ColorSplitter 仓库固定 commit | MIT，17MB |
| `silero_vad.onnx` | Silero VAD 仓库 | MIT，1.9MB |
| `model.int8.onnx` + `tokens.txt` | `csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17` | MIT；239MB + 0.3MB |
| AST AudioSet | Hugging Face `MIT/ast-finetuned-audioset-10-10-0.4593` | BSD-3-Clause |

**重要**：分离模型权重的许可证以模型作者/上游仓库为准，本仓库未对其商用授权做任何保证。若用于商业发布（例如抖音内容生产），请先确认权重来源和授权；不确定时替换为有明确许可的模型或仅用于内部测试。

## 已评估但未默认集成的项目

- **inaVAMOS**（https://github.com/ina-foss/inaVAMOS）：语音/音乐分割精度很高，但使用 Pantagruel Research-only License，仅限研究/ heritage 机构使用，因此不作为默认依赖。若你符合其许可，可在后续以 Engine 形式接入。
- **inaSpeechSegmenter**：MIT，但依赖 TensorFlow，且对带背景音乐的语音召回较弱，未采用。
- **pyannote.audio**：需要 Hugging Face token 和模型许可，未作为默认 diarization 方案。

## 你的责任

- 只处理你拥有版权或已获授权的媒体。
- 不把受版权保护的音乐/电影片段用于未经许可的传播。
- 商用前确认代码、模型权重、ffmpeg 构建三者的许可。

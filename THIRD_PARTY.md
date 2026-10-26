# 第三方项目与归属

AudioLab Studio 只分发自己的编排代码、前端、脚本和文档；上游项目通过 PyPI/模型清单下载，模型权重不进入仓库。

## 代码依赖

| 项目 | 用途 | 许可证 | 链接 |
|---|---|---|---|
| python-audio-separator | 分离模型加载/推理封装 | MIT | https://github.com/nomadkaraoke/python-audio-separator |
| Demucs | 分离模型架构/思路 | MIT | https://github.com/facebookresearch/demucs |
| ColorSplitter | 音色编码器权重与网络定义 | MIT | https://github.com/KakaruHayate/ColorSplitter |
| Resemblyzer | VoiceEncoder 网络定义/预处理 | MIT | https://github.com/resemble-ai/Resemblyzer |
| Silero VAD | 人声活动检测 | MIT | https://github.com/snakers4/silero-vad |
| sherpa-onnx | SenseVoice ONNX 推理 | Apache-2.0 | https://github.com/k2-fsa/sherpa-onnx |
| SenseVoiceSmall | 语音转写 | MIT（SenseVoice / FunASR） | https://github.com/FunAudioLLM/SenseVoice |
| AST AudioSet | 场景标签 | BSD-3-Clause | https://huggingface.co/MIT/ast-finetuned-audioset-10-10-0.4593 |
| librosa | 音频特征/重采样 | ISC | https://librosa.org |
| soundfile | WAV I/O | BSD-3-Clause | https://python-soundfile.readthedocs.io |
| ffmpeg | 编解码/滤镜 | LGPL/GPL（取决于构建） | https://ffmpeg.org |
| FastAPI / Uvicorn | 本地 API | MIT / BSD-3-Clause | https://fastapi.tiangolo.com |
| React / Vite / lucide-react | 工作台前端 | MIT / MIT / ISC | https://react.dev |
| pywebview / pythonnet | 桌面窗口 | BSD-3-Clause / MIT | https://pywebview.flowrl.com |

## 仓库内的第三方派生代码

`src/audiolab/core/timbre_encoder.py` 是为减少安装依赖而**裁剪/改写**的编码器实现，来源于：

- Resemblyzer（MIT）的 `VoiceEncoder` / mel 预处理；
- ColorSplitter（MIT）的推理路径/权重兼容逻辑。

该文件保留来源说明，按 MIT 使用；上游完整代码和版权声明见上述仓库。除该文件外，`src/` 与 `web/src/` 为 AudioLab Studio 原创代码。

如果你不希望仓库包含任何第三方派生代码，可以删除该文件，并在 `requirements.txt` 中加入 ColorSplitter（注意其 git 安装在该 Windows 环境曾遇到克隆不稳定），或改用自己的编码器实现；`timbre.py` 会自动回退 MFCC。

## 模型权重

模型权重**不随仓库分发**，由用户按 [MODELS.md](MODELS.md) 下载。权重许可证以模型作者/上游仓库为准：

- BS-Roformer / UVR-MDX-NET：UVR 社区模型，商用前必须确认授权；
- ColorSplitter `timbre-v1.pt`：MIT；
- Silero VAD：MIT；
- AST：BSD-3-Clause。

本仓库不对模型权重的商用授权做任何保证。

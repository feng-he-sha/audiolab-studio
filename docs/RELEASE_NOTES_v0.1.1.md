# AudioLab Studio v0.1.1

## 新增：SenseVoice 语音转写

- 分析流水线新增 `asr` 阶段：对 `vocals` / `vocals+music` 分段逐段转写，保留原始时间边界，不影响其他阶段。
- 新「转写」Tab：SenseVoice 全文、分段文本、时间、语言、情绪、事件；复制全文；导出 SRT / VTT / TXT。
- 新 API：`GET /api/projects/{id}/transcript` 和 `/transcript/export?format=srt|vtt|txt`。
- 报告新增转写区（全文 + 分段表），`transcript.json` 作为项目产物。
- 模型自动发现：`settings.asr_model_dir` → `AUDIOLAB_SENSEVOICE_DIR` → `models/sensevoice` → 本机 DSH SenseVoice 缓存；缺失时只跳过转写，不阻塞分析。
- 模型中心新增 `asr.sensevoice`（239MB ONNX int8，MIT），`scripts/fetch_models.py --with-asr` 可预下载。
- `sherpa-onnx==2.0.0` 加入依赖；ASR 可选，CPU 即可运行。

## 验证

- `pytest tests -q`：12 passed。
- 真实 29s 视频：14 段转写 / 63 字 / 1.2s，报告含转写区。
- 前端严格 TS 构建通过；新增截图 `web/screenshots/real-transcript.png`。

## 升级

```powershell
git pull
powershell -ExecutionPolicy Bypass -File setup.ps1
```

如果本地已有 SenseVoice（如 `~/.dsh/speech-to-text/sensevoice/models/sensevoice-onnx`），无需下载；否则在「模型」页下载 `asr.sensevoice`，或运行：

```powershell
python scripts\fetch_models.py --model asr.sensevoice
```

# 使用说明

## 启动

```powershell
cd audio-lab
run_workbench.bat
```

首次使用先运行 `setup.ps1`。工作台会打开一个独立窗口（pywebview），失败时自动用默认浏览器打开 `http://127.0.0.1:7861`。

## 导入素材

- 顶部「导入」→ 选择文件/文件夹；
- 或把文件拖进窗口；
- 或在项目库底部输入本地绝对路径；
- 支持音频和视频，视频会自动抽音轨（默认第一条，可在分析参数里改）。

重复文件按 SHA256 去重。

## 一键分析

选中项目 →「一键分析」。阶段：

1. 抽音轨（48k 原声 + 16k 分析）
2. 人声/伴奏分离
3. Silero VAD + 伴奏能量/谐波 + AST 标签
4. 融合成时间轴
5. 音色切片/嵌入/聚类
6. 生成预览、波形峰值、HTML 报告

参数：

| 参数 | 说明 |
|---|---|
| quality | `fast`（MDX，跳 AST）、`balanced`（默认）、`hq`（更高质量分离） |
| separation_model | 手动指定分离模型；留空自动选择 |
| skip_tagging | 跳过 AST，速度快、纯能量判定 |
| clusters | 指定音色簇数；留空自动 |
| timbre_threshold | 余弦聚类阈值，默认 0.35；越小簇越多 |
| timbre_backend | `colorsplitter` 或 `mfcc` |
| force | 忽略缓存全量重跑 |

## 时间轴

- 颜色：人声蓝、音乐绿、混合紫、其他灰。
- 点击分段 → 右侧检查器：置信度、AST 标签、改标签、合并相邻、在播放头切分、恢复自动。
- 顶部标签过滤；`F` 适配视图；空格播放；←/→ seek。
- 参数调整后可「重新融合」，只重跑融合阶段，不重跑分离。

## 分离

- 原声/人声/伴奏三轨，solo/mute/音量；同步播放。
- 导出 stem；处理页会自动使用 stems。

## 音色

- PCA 散点 + 簇卡片；播放代表片段。
- 重命名簇、合并簇；导出簇文件夹。
- 标签是「音高 × 明亮度 × 质感」的启发式描述；F0 仅作参考，不武断判定性别。

## 转写

- 分析完成后打开「转写」页；SenseVoice 会对检测到的人声/混合分段逐段转写。
- 显示全文、时间、语言、情绪、事件；支持复制全文，导出 SRT/VTT/TXT。
- 关闭转写：分析参数里取消「语音转写」，或设置 `asr_enabled=false`。
- 模型缺失时只跳过转写，不影响其他结果；模型路径在设置里可改，或放 `models/sensevoice/`。
- 本机已有 DSH SenseVoice 模型会自动复用，不需要复制。

## 处理

| 预设 | 目标 |
|---|---|
| douyin | -14 LUFS，高通/轻降噪/淡入淡出，适合短视频 |
| podcast | -16 LUFS，降噪+裁静音 |
| movie | -16 LUFS，vocals 触发 instrumental 闪避 |
| music | -14 LUFS，双 stem 混音/人声增强 |
| clean | 裁静音 + 淡入淡出 + 归一化 |

可勾选「视频回贴」生成 `processed/<preset>.mp4`（视频流 copy，不重编码）。

## 批量

项目库多选 → 批量分析/批量处理。任务串行执行，右侧队列显示进度；可取消/重试。

## 模型

模型页显示每个模型的状态/大小/许可证/来源；支持下载、删除、重新校验。默认从镜像下载：

- 分离：`lainlives/audio-separator-models`
- AST：Hugging Face，可设 `HF_ENDPOINT=https://hf-mirror.com`
- 音色/VAD：GitHub / jsDelivr
- 转写：SenseVoice ONNX（`asr.sensevoice`，约 239MB；本机已有会自动复用）

命令行预下载：

```powershell
.\.venv\Scripts\python.exe scripts\fetch_models.py --skip-ast
```

## 设置与诊断

- 设置：工作区/模型目录、设备（auto/cuda/cpu）、HF 镜像、预览质量、主题、语言、ASR 开关/语言/模型目录。
- 诊断：ffmpeg、CUDA、模型、磁盘、权限；可复制诊断信息。
- 日志：右侧任务面板或 `workspace/logs/`。

## 命令行

```powershell
python -m audiolab doctor
python -m audiolab analyze "你的视频.mp4" --quality fast
python -m audiolab process input.mp4 --preset movie --mux-video
python -m audiolab models list
```

## 常见问题

- **前端空白/404**：`pnpm --dir web build`，重启。
- **CUDA 不可用**：检查 `doctor`；CPU 可运行但慢。
- **显存不足**：工作台自动降级 MDX；或设置 `quality=fast`。
- **模型下载卡住**：换 `HF_ENDPOINT`、重试；分离模型可手动放到 `models/separator/`。
- **视频无音轨**：导入会报错；请换有音轨的片段。
- **中文路径**：已用参数列表和 UTF-8 处理；如遇问题把项目放到纯英文路径重试。

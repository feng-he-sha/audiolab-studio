# AudioLab Studio v0.1.0

本地音频人声工作台：统一管理「人声/背景音乐分类 + 人声/伴奏分离 + 按音色聚类 + 简单音频处理」，全部在本地运行。

## 亮点

- 项目库 + 任务队列 + 模型中心 + 诊断日志，一个窗口管理多个上游引擎，不需要逐个打开项目。
- 时间轴：Canvas 波形、分段标签、播放头、改标签/合并/切分/重新融合。
- 逐段时间轴标签：纯人声 / 背景音乐 / 人声+音乐 / 静音·音效，附置信度与 AST 标签。
- 人声/伴奏分离：BS-Roformer（可选下载）或 UVR-MDX-NET Inst HQ 4（CPU 兜底）。
- 音色聚类：ColorSplitter timbre-v1 嵌入 + 余弦层次聚类，输出F0/质心/HNR、代表片段、PCA散点；支持指定簇数。
- 处理预设：`douyin`（-14 LUFS）、`podcast`（-16）、`movie`（BGM 闪避）、`music`、`clean`，支持视频回贴。
- 报告：离线 HTML、音频播放器、ZIP/JSON/CSV 导出。

## 安装

```powershell
git clone https://github.com/feng-he-sha/audiolab-studio.git
cd audiolab-studio
powershell -ExecutionPolicy Bypass -File setup.ps1
run_workbench.bat
```

`setup.ps1` 会安装依赖、构建前端、下载推荐模型（约 80MB）。BS-Roformer（639MB）和 AST（约 350MB）可在「模型」页按需下载。

## 模型与许可证

- 模型权重不随仓库分发，见 `MODELS.md` / `MODELS.json`。
- 上游项目与 MIT 派生编码器说明见 `THIRD_PARTY.md`。
- 分离模型权重为 UVR 社区模型，商用前请确认上游许可。

## 已知限制

- 本机 onnxruntime 无 CUDA provider 时，MDX 分离走 CPU；长视频建议下载 BS-Roformer 使用 GPU。
- AST 未下载时自动跳过场景标签，音乐判定退化为伴奏能量 + 谐波比。
- 单说话人样本自动聚类通常为 1 簇；需要更细分组时在分析参数中指定簇数。

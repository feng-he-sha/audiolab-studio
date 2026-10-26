# 验收与评测记录

测试日期：2026-10-26（Asia/Shanghai）
机器：Windows、Python 3.13.1、RTX 4060 Laptop 8GB、ffmpeg 9.0.2、CUDA 13.0
说明：本机网络较慢，BS-Roformer（639MB）与 AST（约 350MB）未在本轮下载完成；工作台已自动降级到 MDX HQ 4 且跳过 AST，并给出 warning。

## 1. 单元 / 接口测试

```text
pytest tests -q
............ [100%]
12 passed
```

覆盖：

- DB 项目/分段/任务 CRUD、标签覆盖、合并、切分；
- 融合四类标签、静音覆盖、最短段/间隙合并；
- ffmpeg probe/peaks、`clean`/`douyin`/`podcast` 两遍 loudnorm；
- ColorSplitter timbre-v1 权重加载、256 维嵌入归一化；
- SenseVoice 模型发现、SRT/VTT/TXT 字幕导出；
- FastAPI 健康检查/doctor/导入/伪分析/时间轴/音色/转写/产物/报告 `<base>`/人工标签。

## 2. 真实样本全链路

输入：本地测试视频 `测试1.mp4`（不随仓库分发）
时长 29.1627s，1080×1920，AAC 48kHz stereo。

| 指标 | 结果 |
|---|---|
| 导入 | SHA256 去重，项目 `p_6aca8d64887f` |
| 分析（fast，MDX HQ4，CPU） | 完成，wall time **39–41s** |
| 分离 | 23.5s，vocals/instrumental 均 29.1627s，rms 0.205/0.102，相关系数 0.076（确认不是复制） |
| 时间轴 | 15 段（refuse 后） |
| 标签分布 | 人声+音乐 19.68s / 人声 6.66s / 音乐 1.96s / 其他 0.86s |
| 音色 | ColorSplitter backend，1 簇（样本为单一说话人），9 条片段，F0 中位数 211Hz |
| 转写 | SenseVoiceSmall int8（sherpa-onnx/CPU），14 段，1.2s；`transcript.json` 63 字；报告含全文/分段表；样本以歌声/混响为主，文本质量有限，链路正常 |
| 报告 | `report.html` 81KB，离线可开；含转写区；服务端 `<base>` 修复后音频可播放/拖动 |
| 处理 `movie` | -16.0 LUFS，true peak -6.47 dBTP，mux 后 1920×1080 / 29.16s 可播放 |
| 缓存复跑 | 删除 analysis.json 后 balanced 复跑约 12s（复用 stems） |
| 导出 | ZIP/JSON/CSV 均 200；CSV 15 行分段，JSON 含 project/timeline/timbre/artifacts |
| 前端构建 | `pnpm --dir web build` 通过：1 JS（405KB）+ 1 CSS（50KB），dist 无旧 bundle |

截图：

- `web/screenshots/demo-overview.png`：工作台 demo 数据（三栏、队列、模型下载）
- `web/screenshots/real-timeline.png` / `final-timeline.png`：真实项目时间轴（15 段、CUDA、Web Audio）
- `web/screenshots/real-timbre.png`：音色 PCA/簇卡片
- `web/screenshots/real-transcript.png`：真实项目转写页（14 段 / 63 字）
- `web/screenshots/real-overview.png`：真实项目概览
- `web/screenshots/real-report.png`：分析报告（音频已可加载）

## 3. 模型状态

| 模型 | 状态 | 说明 |
|---|---|---|
| MDX HQ 4 | ready | 59MB，CPU 分离 29s 音频约 23s |
| ColorSplitter timbre-v1 | ready | 17MB，GPU 嵌入 9 条片段 <1s |
| Silero VAD ONNX | ready | 1.9MB，29s 音频 0.2s |
| SenseVoiceSmall int8 | ready | 本机 DSH 模型复用，239MB；14 段 1.5s（CPU） |
| BS-Roformer | missing | 639MB 下载受网络限制；自动降级 MDX 并 warning |
| AST AudioSet | missing | 350MB；自动跳过，音乐判定依赖能量/谐波比 |

## 4. 已知限制

- `quality=fast` 使用 MFCC 音色后端；`balanced` 才使用 ColorSplitter。
- 单说话人样本自动阈值得 1 簇；可在分析参数指定 `clusters=2` 观察更细的音色分组。
- BS/AST 未就绪时报告会显示警告；UI 模型页可后续下载。
- 真实电影片段中的音效可能被归入 `other` 或 `music`，建议用 AST + 手动修正。
- 超长视频分离会切块，耗时随长度线性增长；CPU 模式较慢。

# 架构说明

## 1. 总览

```text
┌────────────────────────────── React 工作台（web/） ──────────────────────────────┐
│ 项目库 │ 时间轴/波形 │ 分离试听 │ 音色散点 │ 处理预设 │ 报告 │ 队列/模型/设置/诊断 │
└───────────────▲──────────────────────────────────────────────────────────────────┘
                │ REST + WebSocket（127.0.0.1）
┌───────────────┴──────────────── FastAPI（src/audiolab/server） ──────────────────┐
│ app.py 路由 │ db.py SQLite │ jobs.py 队列 │ events.py WebSocket │ files.py Range │
└───────────────▲──────────────────────────────────────────────────────────────────┘
                │ 子进程 JSONL 进度事件
┌───────────────┴──────────────── Job Worker（jobs/worker.py） ─────────────────────┐
│ pipeline.analyze / pipeline.refuse / pipeline.process / model download            │
│   media → separation → vad → tagging → fusion → timbre → preview/report → process  │
└───────────────▲──────────────────────────────────────────────────────────────────┘
                │
┌───────────────┴──────────────── Engines（engines/ + core/） ───────────────────────┐
│ audio-separator │ Silero VAD │ AST │ ColorSplitter encoder │ ffmpeg presets        │
└────────────────────────────────────────────────────────────────────────────────────┘
```

## 2. 分层

- **core/**：纯音频逻辑，不依赖 FastAPI/DB。输入路径和输出目录，返回 `schemas` 数据类。
- **engines/**：模型/引擎注册表和下载器。UI 只看到 EngineSpec/ModelInfo，不关心上游仓库。
- **server/**：SQLite 持久化、REST、WebSocket、静态文件、任务管理器。
- **jobs/worker.py**：每个任务独立子进程，隔离模型崩溃/OOM；stdout 输出 JSONL。
- **web/**：React SPA，生产构建到 `web/dist` 由 FastAPI 托管；开发时 Vite 代理 `/api`。
- **studio.py**：启动 Uvicorn 线程 + pywebview 窗口；失败时回退浏览器。

## 3. 任务与缓存

- 任务类型：`analyze`、`refuse`（只重跑融合）、`process`、`download`。
- 队列单 worker，GPU 任务串行，避免 8GB 显存竞争。
- 进度事件：`stage` / `progress` / `log` / `done` / `error`；同时写 `workspace/logs/job-*.log`。
- 取消：psutil 终止进程树；启动时把遗留 `running` 标记为 `interrupted`，可重试。
- 阶段缓存：`analysis.json`、`stems/`、`audio/`、`timbre/`、`preview/`、`peaks/`；`force=true` 全量重跑。
- `refuse` 依赖 `evidence.npz`（vocal/music 掩码 + AST 窗口 + RMS），调阈值无需重跑分离。

## 4. 数据库（SQLite WAL）

| 表 | 说明 |
|---|---|
| projects | 项目、源文件、状态、媒体信息、标签汇总、结果目录 |
| runs | 每次分析/处理记录、参数、耗时 |
| segments | 时间轴分段 + 人工覆盖标签 |
| clusters/clips | 音色簇与片段 |
| jobs | 队列/历史/日志路径 |
| models | 模型状态、路径、许可证、下载来源 |
| schema_version | 迁移版本 |

## 5. 音频流水线

1. **probe/extract**：ffprobe + ffmpeg；48k stereo 原声、16k mono 分析音轨。
2. **separation**：audio-separator；BS-Roformer 主模型，MDX ONNX 兜底；5 分钟切块、2s 交叉淡化由分离器/封装处理；OOM/加载失败自动降级。
3. **vad**：Silero ONNX/JIT；人声能量+谐波门限补歌唱；VAD 不可用时能量回退。
4. **tagging**：AST 10s 窗/5s 跳步，关键类别 Music/Speech/Singing/Sound effect 等；缺失时跳过。
5. **fusion**：20ms 帧；vocal/music 掩码 → 四类标签；中值滤波、间隙合并、最短段、边界吸附、置信度、top tags。
6. **timbre**：从 vocal 段切 1.5–10s 片段；ColorSplitter timbre-v1 嵌入 → 余弦层次聚类；F0/质心/rolloff/flatness/HNR；中文簇标签；MFCC 降级。
7. **preview/report**：32k AAC 预览、2000 桶 peaks、离线 HTML 报告、analysis.json。
8. **processing**：两遍 loudnorm；预设 douyin/podcast/movie/music/clean；movie 用 stems sidechain 闪避；`--mux-video` 回贴。

## 6. 前端

- React 19 + TypeScript + Vite；纯 CSS 设计系统；lucide-react 图标。
- 状态：React hooks + 轮询/WS；demo 模式 `?demo=1` 内置数据。
- 时间轴：Canvas 绘制 peaks + 分段 + 标尺 + 播放头；缩放/点击/拖动。
- 播放：Web Audio API 解码 32k AAC 预览；每个 stem 一个 GainNode；同一 `AudioContext.currentTime` 启动；solo/mute/seek/loop。
- 长文件（>10min）降级单轨 `<audio>`，避免解码内存。
- 设置持久化：localStorage（选中项目/tab/主题）+ 后端 settings。

## 7. 失败与降级

| 失败 | 行为 |
|---|---|
| BS-Roformer 缺失/下载失败 | 自动 MDX；`quality=fast` 直接 MDX |
| GPU OOM | 降级 MDX/CPU，任务可重试 |
| AST 模型缺失 | 跳过标签，仅能量/谐波比判定音乐 |
| Silero 缺失/ONNX 损坏 | Silero 包内置模型 → JIT → 能量 VAD |
| ColorSplitter 权重/推理失败 | MFCC 后端 + warning |
| 前端未构建 | 后端返回构建提示页 |
| pywebview 不可用 | 自动浏览器打开 |
| 任务崩溃 | 子进程隔离，标 failed，日志保留，可重试 |

# AudioLab Studio — API Contract (v0.1)

The frontend is a Vite + React SPA served by FastAPI. In dev, Vite runs on
`127.0.0.1:7860` and proxies `/api` to the backend on `127.0.0.1:7861`. In
production, FastAPI serves `web/dist` at `/`.

All payloads are JSON, `snake_case`. All timestamps are ISO-8601 local strings.

## 1. Core entities

```ts
type Label = "vocals" | "music" | "vocals+music" | "other";

interface MediaInfo {
  path: string; filename: string; duration: number;
  sample_rate: number; channels: number; codec: string; bit_rate: number;
  size: number; sha256: string; has_video: boolean;
  video_width?: number | null; video_height?: number | null;
  has_audio: boolean; audio_track: number;
}

interface Project {
  id: string; name: string; source_path: string;
  status: "imported" | "analyzing" | "analyzed" | "processing" | "ready" | "error";
  media?: MediaInfo | null;
  tags: string[];
  summary: Record<string, any>;   // label durations, cluster count, loudness...
  result_dir: string;
  created_at: string; updated_at: string; error: string;
}

interface Segment {
  start: number; stop: number; label: Label;
  confidence: number;
  tags: Record<string, number>;   // top AST tags
  user_label?: string | null;
}

interface Timeline {
  duration: number; frame_hop: number;
  segments: Segment[];
  summary: Record<string, number>; // seconds per label
  warnings: string[];
}

interface TimbreFeatures {
  f0_median?: number | null; f0_mean?: number | null; f0_std?: number | null;
  voiced_ratio: number; centroid_mean: number; centroid_std: number;
  rolloff_mean: number; flatness_mean: number; zcr_mean: number;
  harmonic_ratio: number; rms_db: number; duration: number;
}

interface TimbreClip {
  id: string; path: string; url: string;
  start: number; stop: number; duration: number;
  cluster: number; features: TimbreFeatures; is_representative: boolean;
}

interface TimbreCluster {
  // 全局唯一：`<project_id>:V1`。PATCH /api/clusters/{id} 直接使用此值。
  id: string; index: number; label: string; color: string;
  n_clips: number; total_duration: number;
  features: TimbreFeatures;
  clips: TimbreClip[];
  representative: string[];
  user_label?: string | null;
}

interface TimbreResult {
  backend: "colorsplitter" | "mfcc";
  clusters: TimbreCluster[];
  points: { x: number; y: number; cluster: number; clip_id: string }[];
  warnings: string[];
}

interface TranscriptSegment {
  id: number;
  start: number; stop: number;
  text: string;
  language: string;   // zh | en | ja | ko | yue，可能为空
  emotion: string;    // NEUTRAL / HAPPY / SAD / ANGRY / ...
  event: string;      // Speech / BGM / Applause / ...
}

interface TranscriptResult {
  backend: "sensevoice";
  model_dir: string;
  language: string;
  text: string;
  segments: TranscriptSegment[];
  duration: number;
  elapsed: number;
  warnings: string[];
}

interface Artifact {
  id: string; kind: "original" | "vocals" | "instrumental" | "processed" | "preview" | "report" | "transcript";
  label: string; path: string; url: string;
  duration: number; size: number; mime: string;
}

interface Job {
  id: string; project_id: string;
  kind: "analyze" | "refuse" | "process" | "download";
  status: "queued" | "running" | "done" | "failed" | "canceled" | "interrupted";
  stage: string; progress: number; message: string;
  created_at: string; started_at: string; finished_at: string;
  error: string; params: Record<string, any>;
}
```

## 2. Endpoints

### System / projects

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/api/health` | — | `{ok, version, device, cuda, ffmpeg, web}` |
| GET | `/api/doctor` | — | `{ok, checks:[{name, ok, detail, hint}]}` |
| GET | `/api/projects` | `?query=&status=&page=1&page_size=50` | `{items: Project[], total, page}` |
| POST | `/api/projects/import` | `{paths: string[]}` | `{projects: Project[], errors: string[]}` |
| POST | `/api/projects/upload` | multipart `files` | `{projects: Project[], errors: string[]}` |
| GET | `/api/projects/{id}` | — | `Project` |
| PATCH | `/api/projects/{id}` | `{name?, tags?}` | `Project` |
| DELETE | `/api/projects/{id}` | `?delete_outputs=true` | `{ok}` |
| GET | `/api/projects/{id}/timeline` | — | `Timeline` |
| GET | `/api/projects/{id}/timbre` | — | `TimbreResult` |
| GET | `/api/projects/{id}/transcript` | — | `TranscriptResult`（未转写时 `segments=[]` + warning） |
| GET | `/api/projects/{id}/transcript/export?format=srt\|vtt\|txt` | — | `text/plain` 字幕/文本附件 |
| GET | `/api/projects/{id}/artifacts` | — | `{artifacts: Artifact[]}` |
| GET | `/api/projects/{id}/report` | — | HTML |
| GET | `/api/projects/{id}/export` | `?format=zip` | file download |
| GET | `/api/projects/{id}/peaks/{artifact_id}` | — | `{duration, peaks: [number, number][]}` |
| GET | `/api/files/{project_id}/{path}` | — | file (supports Range) |

### Analysis / processing

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/projects/{id}/analyze` | `{quality?, separation_model?, skip_tagging?, skip_asr?, asr_language?, asr_model_dir?, clusters?, timbre_threshold?, force?}` | `{job_id}` |
| POST | `/api/projects/{id}/refuse` | `{min_segment?, smooth_frames?, min_music?}` | `{job_id}` |
| POST | `/api/projects/{id}/process` | `{preset, params?, mux_video?, output_format?}` | `{job_id}` |

`quality`: `"fast" | "balanced" | "hq"` (default `balanced`).
`preset`: `"douyin" | "podcast" | "movie" | "music" | "clean"`.

### Manual edits

| Method | Path | Body | Returns |
|---|---|---|---|
| PATCH | `/api/projects/{id}/segments/{segment_id}` | `{user_label}` | `Timeline` |
| POST | `/api/projects/{id}/segments/merge` | `{segment_ids: number[]}` | `Timeline` |
| POST | `/api/projects/{id}/segments/split` | `{segment_id, at}` | `Timeline` |
| PATCH | `/api/clusters/{cluster_id}` | `{user_label}` | `TimbreResult` |
| POST | `/api/projects/{id}/clusters/merge` | `{cluster_ids: number[]}` | `TimbreResult` |

### Jobs / models / settings

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/jobs` | `?active=true` | `{items: Job[]}` |
| POST | `/api/jobs/{id}/cancel` | — | `{ok}` |
| POST | `/api/jobs/{id}/retry` | — | `{job_id}` |
| GET | `/api/jobs/{id}/log` | — | `{lines: string[]}` |
| GET | `/api/engines` | — | `{engines: EngineSpec[]}` |
| GET | `/api/models` | — | `{models: ModelInfo[]}` |
| POST | `/api/models/{id}/download` | — | `{job_id}` |
| DELETE | `/api/models/{id}` | — | `{ok}` |
| GET | `/api/settings` | — | `Settings` |
| PATCH | `/api/settings` | partial `Settings` | `Settings` |

### WebSocket

`WS /api/ws/events` — server pushes:

```json
{"type":"job","job":{...}}
{"type":"log","job_id":"...","line":"..."}
{"type":"model","model":{...}}
{"type":"project","project":{...}}
```

Clients may send `{"type":"ping"}`; server replies `{"type":"pong"}`.

## 3. Speech-to-text (SenseVoice)

- Optional stage after timbre, on the vocals stem; it never blocks the rest of
  the analysis if the model/package is missing.
- `skip_asr` defaults to `false`; `asr_language` is `auto|zh|en|ja|ko|yue`;
  `asr_model_dir` overrides auto-discovery.
- Auto-discovery: `settings.asr_model_dir` → `AUDIOLAB_SENSEVOICE_DIR` →
  `models/sensevoice` → `models/sensevoice-onnx` → `~/.dsh/speech-to-text/sensevoice/models/sensevoice-onnx`.
- Model bundle: `model.int8.onnx` + `tokens.txt` (sherpa-onnx SenseVoiceSmall).
- Output: `transcript.json` plus `GET .../transcript`; export `srt`/`vtt`/`txt`.
- Empty transcript is a normal success (`segments=[]`, warning); only model or
  package errors are warnings.

## 4. Import behavior

- `POST /api/projects/import` accepts local absolute paths (the native desktop
  case). Folders are scanned recursively for supported audio/video extensions.
- `POST /api/projects/upload` accepts browser uploads; files are copied into
  `workspace/imports/<id>/`.
- Supported: `.mp3 .wav .flac .m4a .aac .ogg .opus .wma .aiff .aif .mp4 .mov .mkv .webm .avi`.
- Duplicate SHA256 returns the existing project (with `reused: true` in summary).

## 5. UI requirements

Layout: 260px left library, flexible center, 330px right inspector. Dark theme
default. Chinese UI.

- **Topbar**: app name, import button, analyze button, batch process, device
  chip (CUDA/CPU), ffmpeg chip, settings.
- **Library**: search, status filter, project rows with status dot, duration,
  label summary; multi-select; drag/drop import; native dialog via
  `window.pywebview.api.pick_files()` when available, otherwise upload.
- **Project tabs**: 概览 / 时间轴 / 分离 / 音色 / 转写 / 处理 / 报告.
- **Timeline**: canvas waveform + colored segment overlay + ruler + playhead;
  zoom buttons/slider; click to seek; click segment selects it; segment
  inspector allows label override and merge; label filter buttons.
- **Transport**: play/pause, time display, loop; original/vocals/instrumental
  gain + mute + solo. Use Web Audio for synced stems; fall back to `<audio>`.
- **Timbre**: SVG PCA scatter; cluster cards with color, label, F0/centroid,
  play representative clip; rename/merge.
- **Transcript**: full text, copy, SRT/VTT/TXT export; per-segment time/text/
  language/emotion/event table; empty state when ASR is off.
- **Process**: preset cards, parameter controls (target LUFS, denoise, duck,
  output format, mux video), render button, preview player, A/B switch.
- **Queue**: active and recent jobs, progress bar, stage, cancel/retry, log tail.
- **Models**: table/cards with status, size, license, download/delete/test.
- **Settings**: workspace/models dirs, device, HF mirror, theme, language,
  ASR toggle/language/model directory.
- **Doctor**: check list with hints.
- **Report**: iframe pointing at `/api/projects/{id}/report`, open-in-browser
  link and export buttons.

Design tokens:
```
--bg:#0b0e14; --panel:#121722; --panel-2:#171e2b; --line:#263041;
--text:#e6edf7; --muted:#8b9bb4; --accent:#5eead4; --accent-2:#38bdf8;
--vocals:#60a5fa; --music:#34d399; --mixed:#a78bfa; --other:#94a3b8;
--danger:#f87171; --warn:#fbbf24;
font: "Segoe UI", "Microsoft YaHei UI", system-ui, sans-serif;
```
Use inline SVG icons from `lucide-react`. Avoid external fonts/CDNs.

## 6. Build / dev

```bash
pnpm --dir web install
pnpm --dir web build          # outputs web/dist, served by FastAPI
pnpm --dir web dev            # http://127.0.0.1:7860 with /api proxy
```

Fake mode for UI development: backend env `AUDIOLAB_FAKE=1` returns synthetic
timeline/timbre quickly; no models required.

## 7. Interaction rules

- Never block the UI on a job: submit then poll `/api/jobs` and/or use WS.
- After a job finishes, refresh project, timeline, timbre, artifacts.
- Show errors from `job.error` and `/api/doctor`.
- Persist selected project/tab/theme in `localStorage`.
- All audio URLs are relative and must be played via the API origin.

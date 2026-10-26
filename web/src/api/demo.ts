/**
 * Self-contained demo backend for visual acceptance and screenshots.
 * Activated with `?demo=1` or `VITE_DEMO=1`. No network calls are made.
 */
import type {
  ApiClient,
  Artifact,
  DoctorResult,
  Health,
  ImportResult,
  Job,
  JobSummary,
  MediaInfo,
  ModelInfo,
  PagedProjects,
  Peaks,
  ProcessOptions,
  Project,
  ServerEvent,
  Settings,
  Timeline,
  TimbreCluster,
  TimbreResult,
} from "./types";

export function demoEnabled(): boolean {
  try {
    const params = new URLSearchParams(window.location.search);
    const q = params.get("demo");
    if (q === "1" || q === "true" || q === "yes") return true;
  } catch {
    /* ignore */
  }
  const env = import.meta.env.VITE_DEMO as string | undefined;
  return env === "1" || env === "true";
}

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

const now = () => new Date().toISOString();
const minutesAgo = (m: number) =>
  new Date(Date.now() - m * 60_000).toISOString();

function media(partial: Partial<MediaInfo> & { filename: string; duration: number }): MediaInfo {
  const { filename, duration, ...rest } = partial;
  return {
    path: `E:\\AudioLab\\demo\\${filename}`,
    sample_rate: 48000,
    channels: 2,
    codec: "aac",
    bit_rate: 192000,
    size: 3_842_116,
    sha256: "9f2c4ab71d3e0c5f6a8b1d2e3f405162738495a6b7c8d9e0f1a2b3c4d5e6f708",
    has_video: true,
    video_width: 1080,
    video_height: 1920,
    has_audio: true,
    audio_track: 0,
    ...rest,
    filename,
    duration,
  };
}

function features(partial: Partial<TimbreResult["clusters"][number]["features"]>): TimbreResult["clusters"][number]["features"] {
  return {
    f0_median: 112.4,
    f0_mean: 118.2,
    f0_std: 15.6,
    voiced_ratio: 0.76,
    centroid_mean: 1480,
    centroid_std: 220,
    rolloff_mean: 2650,
    flatness_mean: 0.021,
    zcr_mean: 0.061,
    harmonic_ratio: 0.72,
    rms_db: -18.4,
    duration: 11.8,
    ...partial,
  };
}

/** Deterministic waveform-ish peaks (min/max pairs) used for the canvas. */
function makePeaks(duration: number, seed: number): Peaks {
  const n = Math.max(280, Math.min(4000, Math.round(duration * 44)));
  const peaks: [number, number][] = [];
  for (let i = 0; i < n; i += 1) {
    const t = i / n;
    const speech = Math.pow(Math.abs(Math.sin(t * Math.PI * 7.3 + seed)), 1.8);
    const music = 0.42 * Math.pow(Math.abs(Math.sin(t * Math.PI * 23.1 + seed * 2)), 3.2);
    const envelope = 0.18 + 0.72 * speech + music;
    const jitter = 0.12 * Math.sin(i * 12.9898 + seed) + 0.07 * Math.sin(i * 78.233 + seed * 3);
    const amp = Math.min(1, Math.max(0.03, envelope * 0.85 + jitter));
    const min = -amp * (0.82 + 0.18 * Math.sin(i * 0.7));
    const max = amp * (0.8 + 0.2 * Math.cos(i * 0.53));
    peaks.push([Number(min.toFixed(4)), Number(max.toFixed(4))]);
  }
  return { duration, peaks };
}

function summarize(segments: Timeline["segments"]): Record<string, number> {
  const summary: Record<string, number> = { vocals: 0, music: 0, "vocals+music": 0, other: 0 };
  for (const seg of segments) {
    summary[seg.label] = Number(((summary[seg.label] ?? 0) + (seg.stop - seg.start)).toFixed(2));
  }
  return summary;
}

function makeTimeline(duration: number, segments: Timeline["segments"]): Timeline {
  return {
    duration,
    frame_hop: 0.02,
    segments,
    summary: summarize(segments),
    warnings: [],
  };
}

/* ------------------------------------------------------------------ */
/* Static demo datasets                                                */
/* ------------------------------------------------------------------ */

const P1 = "p-29s";
const P2 = "p-podcast";
const P3 = "p-mv";

const p1Segments: Timeline["segments"] = [
  { id: 1, start: 0, stop: 1.8, label: "other", confidence: 0.62, tags: { Music: 0.44, Speech: 0.31 }, user_label: null },
  { id: 2, start: 1.8, stop: 6.4, label: "vocals", confidence: 0.93, tags: { Speech: 0.95, Singing: 0.21 }, user_label: null },
  { id: 3, start: 6.4, stop: 9.0, label: "music", confidence: 0.86, tags: { Music: 0.91, Speech: 0.12 }, user_label: null },
  { id: 4, start: 9.0, stop: 14.6, label: "vocals+music", confidence: 0.74, tags: { Speech: 0.62, Music: 0.58 }, user_label: null },
  { id: 5, start: 14.6, stop: 19.2, label: "vocals", confidence: 0.9, tags: { Speech: 0.92 }, user_label: null },
  { id: 6, start: 19.2, stop: 22.8, label: "music", confidence: 0.81, tags: { Music: 0.87 }, user_label: null },
  { id: 7, start: 22.8, stop: 27.4, label: "vocals", confidence: 0.89, tags: { Speech: 0.9 }, user_label: null },
  { id: 8, start: 27.4, stop: 29.4, label: "other", confidence: 0.55, tags: { Music: 0.35, Speech: 0.2 }, user_label: null },
];

const p3Segments: Timeline["segments"] = [
  { id: 1, start: 0, stop: 4.2, label: "music", confidence: 0.88, tags: { Music: 0.9 }, user_label: null },
  { id: 2, start: 4.2, stop: 12.6, label: "vocals+music", confidence: 0.79, tags: { Speech: 0.7, Music: 0.66 }, user_label: null },
  { id: 3, start: 12.6, stop: 20.4, label: "vocals", confidence: 0.91, tags: { Singing: 0.88 }, user_label: null },
  { id: 4, start: 20.4, stop: 28.8, label: "music", confidence: 0.85, tags: { Music: 0.89 }, user_label: null },
  { id: 5, start: 28.8, stop: 36.2, label: "vocals+music", confidence: 0.76, tags: { Speech: 0.64, Music: 0.61 }, user_label: null },
  { id: 6, start: 36.2, stop: 45.2, label: "music", confidence: 0.9, tags: { Music: 0.93 }, user_label: null },
];

function cluster(
  index: number,
  id: string,
  label: string,
  color: string,
  clips: { id: string; start: number; stop: number }[],
  feat: TimbreResult["clusters"][number]["features"],
): TimbreCluster {
  const n = clips.length;
  return {
    id,
    index,
    label,
    color,
    n_clips: n,
    total_duration: Number(clips.reduce((a, c) => a + (c.stop - c.start), 0).toFixed(2)),
    features: feat,
    clips: clips.map((c, i) => ({
      id: c.id,
      path: `E:\\AudioLab\\demo\\clips\\${c.id}.wav`,
      url: `/api/files/${P1}/clips/${c.id}.wav`,
      start: c.start,
      stop: c.stop,
      duration: Number((c.stop - c.start).toFixed(2)),
      cluster: index,
      features: feat,
      is_representative: i === 0,
    })),
    representative: clips.slice(0, 1).map((c) => c.id),
    user_label: null,
  };
}

const maleCluster = cluster(
  0,
  "cluster-p1-a",
  "男声 · 低沉",
  "#38bdf8",
  [
    { id: "clip-a1", start: 1.8, stop: 3.4 },
    { id: "clip-a2", start: 4.2, stop: 6.4 },
    { id: "clip-a3", start: 14.6, stop: 16.9 },
    { id: "clip-a4", start: 17.4, stop: 19.2 },
    { id: "clip-a5", start: 22.8, stop: 25.1 },
    { id: "clip-a6", start: 25.8, stop: 27.4 },
  ],
  features({
    f0_median: 108.5,
    f0_mean: 112.3,
    f0_std: 14.2,
    voiced_ratio: 0.78,
    centroid_mean: 1420,
    centroid_std: 210,
    rolloff_mean: 2600,
    flatness_mean: 0.021,
    zcr_mean: 0.061,
    harmonic_ratio: 0.72,
    rms_db: -18.4,
    duration: 11.8,
  }),
);

const femaleCluster = cluster(
  1,
  "cluster-p1-b",
  "女声 · 明亮",
  "#f472b6",
  [
    { id: "clip-b1", start: 9.2, stop: 11.4 },
    { id: "clip-b2", start: 12.0, stop: 14.6 },
    { id: "clip-b3", start: 19.4, stop: 21.0 },
  ],
  features({
    f0_median: 226.4,
    f0_mean: 232.8,
    f0_std: 22.1,
    voiced_ratio: 0.71,
    centroid_mean: 2380,
    centroid_std: 340,
    rolloff_mean: 4100,
    flatness_mean: 0.032,
    zcr_mean: 0.084,
    harmonic_ratio: 0.66,
    rms_db: -20.1,
    duration: 6.4,
  }),
);

function pointsFor(clusters: TimbreCluster[]): TimbreResult["points"] {
  const points: TimbreResult["points"] = [];
  const centers: [number, number][] = [
    [-1.15, 0.42],
    [1.22, -0.48],
    [0.12, 1.15],
    [-0.6, -1.1],
  ];
  clusters.forEach((c, ci) => {
    const [cx, cy] = centers[ci % centers.length];
    c.clips.forEach((clip, i) => {
      const angle = (i / Math.max(1, c.clips.length)) * Math.PI * 2 + ci;
      const radius = 0.28 + 0.22 * Math.sin(i * 2.7 + ci);
      points.push({
        x: Number((cx + Math.cos(angle) * radius).toFixed(3)),
        y: Number((cy + Math.sin(angle) * radius * 0.8).toFixed(3)),
        cluster: c.index,
        clip_id: clip.id,
      });
    });
  });
  return points;
}

const p1Timbre: TimbreResult = {
  backend: "colorsplitter",
  clusters: [maleCluster, femaleCluster],
  points: pointsFor([maleCluster, femaleCluster]),
  warnings: [],
};

const p3ClusterA = cluster(
  0,
  "cluster-p3-a",
  "主唱 · 中高音",
  "#a78bfa",
  [
    { id: "clip-c1", start: 5.0, stop: 9.2 },
    { id: "clip-c2", start: 13.0, stop: 17.4 },
  ],
  features({ f0_median: 196.2, centroid_mean: 2050, harmonic_ratio: 0.69, rms_db: -16.9, duration: 8.6 }),
);
const p3ClusterB = cluster(
  1,
  "cluster-p3-b",
  "和声 · 气声",
  "#34d399",
  [
    { id: "clip-d1", start: 22.0, stop: 26.4 },
    { id: "clip-d2", start: 30.0, stop: 33.8 },
  ],
  features({ f0_median: 248.6, centroid_mean: 3120, harmonic_ratio: 0.58, rms_db: -22.3, duration: 8.2 }),
);

const p3Timbre: TimbreResult = {
  backend: "colorsplitter",
  clusters: [p3ClusterA, p3ClusterB],
  points: pointsFor([p3ClusterA, p3ClusterB]),
  warnings: [],
};

function artifactsFor(projectId: string, duration: number, processed: boolean): Artifact[] {
  const list: Artifact[] = [
    {
      id: `${projectId}-original`,
      kind: "original",
      label: "原声",
      path: `E:\\AudioLab\\demo\\${projectId}\\original.mp4`,
      url: `/api/files/${projectId}/original.mp4`,
      duration,
      size: 3_842_116,
      mime: "video/mp4",
    },
    {
      id: `${projectId}-vocals`,
      kind: "vocals",
      label: "人声",
      path: `E:\\AudioLab\\demo\\${projectId}\\vocals.wav`,
      url: `/api/files/${projectId}/vocals.wav`,
      duration,
      size: 5_643_332,
      mime: "audio/wav",
    },
    {
      id: `${projectId}-instrumental`,
      kind: "instrumental",
      label: "伴奏",
      path: `E:\\AudioLab\\demo\\${projectId}\\instrumental.wav`,
      url: `/api/files/${projectId}/instrumental.wav`,
      duration,
      size: 5_643_332,
      mime: "audio/wav",
    },
    {
      id: `${projectId}-preview`,
      kind: "preview",
      label: "预览 · m4a",
      path: `E:\\AudioLab\\demo\\${projectId}\\preview.m4a`,
      url: `/api/files/${projectId}/preview.m4a`,
      duration,
      size: 1_024_000,
      mime: "audio/mp4",
    },
    {
      id: `${projectId}-report`,
      kind: "report",
      label: "分析报告",
      path: `E:\\AudioLab\\demo\\${projectId}\\report.html`,
      url: `/api/projects/${projectId}/report`,
      duration: 0,
      size: 48_210,
      mime: "text/html",
    },
  ];
  if (processed) {
    list.push({
      id: `${projectId}-processed`,
      kind: "processed",
      label: "处理结果 · 抖音",
      path: `E:\\AudioLab\\demo\\${projectId}\\processed_douyin.m4a`,
      url: `/api/files/${projectId}/processed_douyin.m4a`,
      duration,
      size: 1_384_220,
      mime: "audio/mp4",
    });
  }
  return list;
}

const projects: Project[] = [
  {
    id: P1,
    name: "测试视频_抖音口播_29s",
    source_path: "E:\\AudioLab\\demo\\测试视频_抖音口播_29s.mp4",
    status: "analyzed",
    media: media({ filename: "测试视频_抖音口播_29s.mp4", duration: 29.4 }),
    tags: ["口播", "人声为主", "2 个音色簇"],
    summary: {
      vocals: 13.8,
      music: 6.2,
      "vocals+music": 5.6,
      other: 3.8,
      clusters: 2,
      integrated_lufs: -16.8,
      true_peak_dbtp: -1.2,
      lra: 6.4,
    },
    result_dir: `E:\\AudioLab\\workspace\\${P1}`,
    created_at: minutesAgo(48),
    updated_at: minutesAgo(3),
    error: "",
  },
  {
    id: P3,
    name: "音乐MV_副歌_竖屏",
    source_path: "E:\\AudioLab\\demo\\音乐MV_副歌_竖屏.mp4",
    status: "ready",
    media: media({
      filename: "音乐MV_副歌_竖屏.mp4",
      duration: 45.2,
      bit_rate: 256000,
      size: 8_112_400,
    }),
    tags: ["音乐", "已处理", "抖音预设"],
    summary: {
      music: 19.8,
      vocals: 7.8,
      "vocals+music": 17.6,
      other: 0,
      clusters: 2,
      integrated_lufs: -14.0,
      true_peak_dbtp: -1.0,
      lra: 5.1,
      preset: "douyin",
    },
    result_dir: `E:\\AudioLab\\workspace\\${P3}`,
    created_at: minutesAgo(180),
    updated_at: minutesAgo(26),
    error: "",
  },
  {
    id: P2,
    name: "播客EP12_访谈片段",
    source_path: "E:\\AudioLab\\demo\\播客EP12_访谈片段.wav",
    status: "imported",
    media: media({
      filename: "播客EP12_访谈片段.wav",
      duration: 1873.2,
      codec: "pcm_s24le",
      bit_rate: 2304000,
      size: 53_948_112,
      has_video: false,
      video_width: null,
      video_height: null,
    }),
    tags: ["播客", "长音频"],
    summary: { duration: 1873.2 },
    result_dir: `E:\\AudioLab\\workspace\\${P2}`,
    created_at: minutesAgo(12),
    updated_at: minutesAgo(12),
    error: "",
  },
];

const timelines: Record<string, Timeline> = {
  [P1]: makeTimeline(29.4, p1Segments),
  [P3]: makeTimeline(45.2, p3Segments),
};

const timbres: Record<string, TimbreResult> = {
  [P1]: p1Timbre,
  [P3]: p3Timbre,
};

const artifacts: Record<string, Artifact[]> = {
  [P1]: artifactsFor(P1, 29.4, false),
  [P3]: artifactsFor(P3, 45.2, true),
  [P2]: [],
};

const models: ModelInfo[] = [
  {
    id: "silero-vad",
    engine: "vad",
    filename: "silero_vad.onnx",
    label: "Silero VAD",
    size: 2_177_280,
    status: "ready",
    path: "E:\\AudioLab\\models\\silero_vad.onnx",
    license: "MIT",
    source: "https://github.com/snakers4/silero-vad",
    sha256: "a3b1c9…",
    error: "",
  },
  {
    id: "ast-audioset",
    engine: "tagging",
    filename: "ast-audioset-best.pth",
    label: "AST AudioSet (音频标签)",
    size: 362_807_296,
    status: "missing",
    path: "E:\\AudioLab\\models\\ast-audioset-best.pth",
    license: "MIT",
    source: "https://huggingface.co/MIT/ast-finetuned-audioset-10-10-0.4593",
    sha256: "",
    error: "",
  },
  {
    id: "bs-roformer",
    engine: "separation",
    filename: "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
    label: "BS-Roformer 人声分离",
    size: 639_000_000,
    status: "downloading",
    path: "E:\\AudioLab\\models\\model_bs_roformer.ckpt",
    license: "MIT",
    source: "https://huggingface.co/audio-separator/BS-Roformer",
    sha256: "",
    error: "",
  },
  {
    id: "mdx-net",
    engine: "separation",
    filename: "UVR-MDX-NET-Inst_HQ_3.onnx",
    label: "MDX-NET 兜底分离",
    size: 64_000_000,
    status: "ready",
    path: "E:\\AudioLab\\models\\UVR-MDX-NET-Inst_HQ_3.onnx",
    license: "MIT",
    source: "https://huggingface.co/audio-separator",
    sha256: "77fd0a…",
    error: "",
  },
  {
    id: "colorsplitter",
    engine: "timbre",
    filename: "colorsplitter",
    label: "ColorSplitter 音色聚类",
    size: 18_400_000,
    status: "ready",
    path: "E:\\AudioLab\\models\\colorsplitter",
    license: "Apache-2.0",
    source: "https://github.com/KakaruHayate/ColorSplitter",
    sha256: "",
    error: "",
  },
];

const jobs: Job[] = [
  {
    id: "job-1031",
    project_id: P1,
    kind: "analyze",
    status: "done",
    stage: "完成",
    progress: 1,
    message: "分析完成：8 个分段 · 2 个音色簇",
    created_at: minutesAgo(9),
    started_at: minutesAgo(9),
    finished_at: minutesAgo(6),
    error: "",
    params: { quality: "balanced" },
  },
  {
    id: "job-1032",
    project_id: "",
    kind: "download",
    status: "running",
    stage: "下载 BS-Roformer (639 MB)",
    progress: 0.62,
    message: "已下载 396 MB / 639 MB · 4.2 MB/s",
    created_at: minutesAgo(7),
    started_at: minutesAgo(7),
    finished_at: "",
    error: "",
    params: { model_id: "bs-roformer" },
  },
  {
    id: "job-1029",
    project_id: P3,
    kind: "process",
    status: "done",
    stage: "完成",
    progress: 1,
    message: "已输出 抖音预设 · -14.0 LUFS / -1.0 dBTP",
    created_at: minutesAgo(31),
    started_at: minutesAgo(30),
    finished_at: minutesAgo(26),
    error: "",
    params: { preset: "douyin" },
  },
  {
    id: "job-1027",
    project_id: P2,
    kind: "analyze",
    status: "failed",
    stage: "加载 VAD 模型",
    progress: 0.08,
    message: "",
    created_at: minutesAgo(11),
    started_at: minutesAgo(11),
    finished_at: minutesAgo(10),
    error: "模型缺失：silero-vad 尚未下载，请到「模型」页下载后重试。",
    params: { quality: "fast" },
  },
  {
    id: "job-1030",
    project_id: P2,
    kind: "analyze",
    status: "queued",
    stage: "排队中",
    progress: 0,
    message: "等待 GPU 任务槽位",
    created_at: minutesAgo(2),
    started_at: "",
    finished_at: "",
    error: "",
    params: { quality: "balanced" },
  },
];

const logs: Record<string, string[]> = {
  "job-1032": [
    "[download] 解析模型清单 bs-roformer",
    "[download] 源 https://hf-mirror.com/audio-separator/BS-Roformer",
    "[download] 396.0 / 639.0 MB (62%) · 4.2 MB/s",
    "[download] 剩余约 58s",
  ],
  "job-1031": [
    "[analyze] 项目 p-29s · quality=balanced",
    "[media] ffprobe: aac 48kHz stereo · 29.40s · 1080x1920",
    "[vad] Silero VAD: 41 个语音片段",
    "[tagging] AST: 8 段标签完成",
    "[timbre] ColorSplitter: 2 个簇 / 9 个片段",
    "[separate] BS-Roformer 完成，人声 + 伴奏已写入 artifacts",
    "[report] report.html 已生成",
    "[done] 用时 3m12s",
  ],
  "job-1027": [
    "[analyze] 项目 p-podcast · quality=fast",
    "[models] 检查 silero-vad … missing",
    "[error] 模型缺失：silero-vad",
  ],
  "job-1029": [
    "[process] preset=douyin target=-14 LUFS",
    "[loudnorm] pass1: -18.4 LUFS",
    "[loudnorm] pass2: -14.0 LUFS / -1.0 dBTP",
    "[mux] 视频回贴 1080x1920",
    "[done] outputs/processed_douyin.m4a",
  ],
};

const settings: Settings = {
  workspace_dir: "E:\\AudioLab\\workspace",
  models_dir: "E:\\AudioLab\\models",
  device: "auto",
  hf_endpoint: "https://hf-mirror.com",
  preview_quality: 32,
  max_gpu_jobs: 1,
  theme: "dark",
  language: "zh-CN",
  auto_open_report: false,
};

const doctor: DoctorResult = {
  ok: false,
  checks: [
    {
      name: "Python 运行时",
      ok: true,
      detail: "Python 3.11.9 (E:\\AudioLab\\.venv)",
      hint: "",
    },
    {
      name: "ffmpeg / ffprobe",
      ok: true,
      detail: "ffmpeg 7.1 · E:\\AudioLab\\bin\\ffmpeg.exe",
      hint: "",
    },
    {
      name: "GPU / CUDA",
      ok: true,
      detail: "未检测到 NVIDIA GPU，按 CPU 模式运行（分离速度约慢 4 倍）",
      hint: "如需加速请安装 CUDA 版 PyTorch。",
    },
    {
      name: "VAD 模型",
      ok: true,
      detail: "silero_vad.onnx · 2.1 MB",
      hint: "",
    },
    {
      name: "AST 标签模型",
      ok: false,
      detail: "ast-audioset-best.pth 缺失",
      hint: "在「模型」页点击下载（约 346 MB）；缺失时会跳过 AST 标签，融合仍可用。",
    },
    {
      name: "工作区可写",
      ok: true,
      detail: "E:\\AudioLab\\workspace · 剩余 184 GB",
      hint: "",
    },
    {
      name: "后端端口",
      ok: true,
      detail: "127.0.0.1:7861 监听中",
      hint: "",
    },
  ],
};

const health: Health = {
  ok: true,
  version: "0.1.0",
  device: "cpu",
  cuda: false,
  ffmpeg: true,
  web: true,
};

/* ------------------------------------------------------------------ */
/* Mutation helpers                                                    */
/* ------------------------------------------------------------------ */

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function findProject(id: string): Project {
  const project = projects.find((p) => p.id === id);
  if (!project) throw new Error(`项目不存在：${id}`);
  return project;
}

function findCluster(clusterId: string): { projectId: string; cluster: TimbreCluster } {
  for (const [projectId, timbre] of Object.entries(timbres)) {
    const found = timbre.clusters.find((c) => c.id === clusterId);
    if (found) return { projectId, cluster: found };
  }
  throw new Error(`音色簇不存在：${clusterId}`);
}

/* ------------------------------------------------------------------ */
/* Live job simulation                                                 */
/* ------------------------------------------------------------------ */

type Listener = (event: ServerEvent) => void;
const listeners = new Set<Listener>();

function emit(event: ServerEvent): void {
  for (const listener of Array.from(listeners)) {
    try {
      listener(event);
    } catch {
      /* ignore listener errors */
    }
  }
}

const timers = new Map<string, number>();

function stopTimer(jobId: string): void {
  const timer = timers.get(jobId);
  if (timer !== undefined) {
    window.clearInterval(timer);
    timers.delete(jobId);
  }
}

function emitJob(job: Job): void {
  emit({ type: "job", job: clone(job) });
}

function finishJob(job: Job, message: string): void {
  job.status = "done";
  job.stage = "完成";
  job.progress = 1;
  job.message = message;
  job.finished_at = now();
  stopTimer(job.id);
  emitJob(job);
  logs[job.id] = [...(logs[job.id] ?? []), `[done] ${message}`];
}

function startAnalyzeJob(project: Project): Job {
  project.status = "analyzing";
  project.error = "";
  project.updated_at = now();
  emit({ type: "project", project: clone(project) });

  const job: Job = {
    id: `job-${Date.now().toString(36)}`,
    project_id: project.id,
    kind: "analyze",
    status: "running",
    stage: "准备中",
    progress: 0.02,
    message: "初始化分析流水线",
    created_at: now(),
    started_at: now(),
    finished_at: "",
    error: "",
    params: { quality: "balanced" },
  };
  jobs.unshift(job);
  logs[job.id] = [`[analyze] 项目 ${project.id} · 演示流水线`];
  emitJob(job);

  const stages: [string, number, string][] = [
    ["媒体探测", 0.16, "ffprobe 读取媒体信息"],
    ["语音检测 (VAD)", 0.34, "Silero VAD 逐帧检测"],
    ["AST 标签", 0.52, "音频事件标签推理"],
    ["证据融合", 0.7, "20ms 帧级融合与平滑"],
    ["音色聚类", 0.86, "ColorSplitter 嵌入聚类"],
    ["分离与报告", 0.96, "生成 stems 与分析报告"],
  ];
  let step = 0;
  const timer = window.setInterval(() => {
    if (job.status !== "running") {
      stopTimer(job.id);
      return;
    }
    const stage = stages[step];
    if (stage) {
      job.stage = stage[0];
      job.progress = stage[1];
      job.message = stage[2];
      logs[job.id] = [...(logs[job.id] ?? []), `[${stage[0]}] ${stage[2]}`];
      emitJob(job);
      emit({ type: "log", job_id: job.id, line: `[${stage[0]}] ${stage[2]}` });
      step += 1;
      return;
    }
    const duration = project.media?.duration ?? 29.4;
    if (!timelines[project.id]) {
      const segs = makeTimeline(duration, p1Segments.map((s) => ({ ...s, user_label: null }))).segments;
      timelines[project.id] = makeTimeline(duration, segs);
    }
    if (!timbres[project.id]) timbres[project.id] = clone(p1Timbre);
    if (!artifacts[project.id]) artifacts[project.id] = artifactsFor(project.id, duration, false);
    project.status = "analyzed";
    project.tags = ["演示", "已分析"];
    project.summary = {
      ...timelines[project.id].summary,
      clusters: timbres[project.id].clusters.length,
      integrated_lufs: -17.2,
    };
    project.updated_at = now();
    finishJob(job, "分析完成：8 个分段 · 2 个音色簇");
    emit({ type: "project", project: clone(project) });
  }, 900);
  timers.set(job.id, timer);
  return job;
}

function startProcessJob(project: Project, opts: ProcessOptions): Job {
  project.status = "processing";
  project.updated_at = now();
  emit({ type: "project", project: clone(project) });
  const job: Job = {
    id: `job-${Date.now().toString(36)}`,
    project_id: project.id,
    kind: "process",
    status: "running",
    stage: "准备中",
    progress: 0.05,
    message: `预设 ${opts.preset}`,
    created_at: now(),
    started_at: now(),
    finished_at: "",
    error: "",
    params: opts as unknown as Record<string, unknown>,
  };
  jobs.unshift(job);
  logs[job.id] = [`[process] preset=${opts.preset} format=${opts.output_format ?? "m4a"}`];
  emitJob(job);
  const stages: [string, number, string][] = [
    ["降噪", 0.24, "频谱降噪"],
    ["EQ / 压缩", 0.46, "音色塑形"],
    ["响度归一", 0.72, "两遍 loudnorm"],
    ["侧链闪避", 0.86, "人声触发音乐闪避"],
    ["封装输出", 0.96, opts.mux_video ? "回贴视频轨道" : "封装音频"],
  ];
  let step = 0;
  const timer = window.setInterval(() => {
    if (job.status !== "running") {
      stopTimer(job.id);
      return;
    }
    const stage = stages[step];
    if (stage) {
      job.stage = stage[0];
      job.progress = stage[1];
      job.message = stage[2];
      logs[job.id] = [...(logs[job.id] ?? []), `[${stage[0]}] ${stage[2]}`];
      emitJob(job);
      step += 1;
      return;
    }
    const list = artifacts[project.id] ?? [];
    const filtered = list.filter((a) => a.kind !== "processed");
    filtered.push({
      id: `${project.id}-processed`,
      kind: "processed",
      label: `处理结果 · ${opts.preset}`,
      path: `E:\\AudioLab\\demo\\${project.id}\\processed_${opts.preset}.m4a`,
      url: `/api/files/${project.id}/processed_${opts.preset}.m4a`,
      duration: project.media?.duration ?? 0,
      size: 1_384_220,
      mime: "audio/mp4",
    });
    artifacts[project.id] = filtered;
    project.status = "ready";
    project.updated_at = now();
    project.summary = { ...project.summary, preset: opts.preset, integrated_lufs: -14.0 };
    finishJob(job, `已输出 ${opts.preset} 预设 · -14.0 LUFS`);
    emit({ type: "project", project: clone(project) });
  }, 850);
  timers.set(job.id, timer);
  return job;
}

function startRefuseJob(project: Project): Job {
  const job: Job = {
    id: `job-${Date.now().toString(36)}`,
    project_id: project.id,
    kind: "refuse",
    status: "running",
    stage: "重新融合",
    progress: 0.15,
    message: "应用最短段 / 平滑帧 / 音乐门限",
    created_at: now(),
    started_at: now(),
    finished_at: "",
    error: "",
    params: {},
  };
  jobs.unshift(job);
  emitJob(job);
  let progress = 0.15;
  const timer = window.setInterval(() => {
    if (job.status !== "running") {
      stopTimer(job.id);
      return;
    }
    progress = Math.min(0.95, progress + 0.18);
    job.progress = progress;
    job.stage = progress > 0.6 ? "平滑分段" : "重新融合";
    emitJob(job);
    if (progress >= 0.95) {
      finishJob(job, "时间轴已重新融合");
      emit({ type: "project", project: clone(project) });
    }
  }, 500);
  timers.set(job.id, timer);
  return job;
}

function startDownloadJob(model: ModelInfo): Job {
  model.status = "downloading";
  emit({ type: "model", model: clone(model) });
  const job: Job = {
    id: `job-${Date.now().toString(36)}`,
    project_id: "",
    kind: "download",
    status: "running",
    stage: `下载 ${model.label}`,
    progress: 0.02,
    message: "连接模型源…",
    created_at: now(),
    started_at: now(),
    finished_at: "",
    error: "",
    params: { model_id: model.id },
  };
  jobs.unshift(job);
  logs[job.id] = [`[download] 开始下载 ${model.label}`];
  emitJob(job);
  let progress = 0.02;
  const timer = window.setInterval(() => {
    if (job.status !== "running") {
      stopTimer(job.id);
      return;
    }
    progress = Math.min(0.99, progress + 0.06);
    const done = Math.round(progress * model.size);
    job.progress = progress;
    job.stage = `下载 ${model.label}`;
    job.message = `已下载 ${(done / 1024 / 1024).toFixed(0)} MB / ${(model.size / 1024 / 1024).toFixed(0)} MB`;
    emitJob(job);
    if (progress >= 0.99) {
      model.status = "ready";
      finishJob(job, `${model.label} 下载完成`);
      emit({ type: "model", model: clone(model) });
    }
  }, 700);
  timers.set(job.id, timer);
  return job;
}

/** Slow background progress for the initially running download job. */
let liveTickStarted = false;
function startLiveTick(): void {
  if (liveTickStarted) return;
  liveTickStarted = true;
  window.setInterval(() => {
    const job = jobs.find((j) => j.id === "job-1032");
    if (!job || job.status !== "running") return;
    job.progress = Math.min(0.96, job.progress + 0.01);
    const model = models.find((m) => m.id === "bs-roformer");
    if (model) {
      const done = Math.round(job.progress * model.size);
      job.message = `已下载 ${(done / 1024 / 1024).toFixed(0)} MB / ${(model.size / 1024 / 1024).toFixed(0)} MB`;
      if (job.progress >= 0.96) {
        model.status = "ready";
        finishJob(job, "BS-Roformer 下载完成");
        emit({ type: "model", model: clone(model) });
      }
    }
    emitJob(job);
  }, 2200);
}

/* ------------------------------------------------------------------ */
/* Demo report HTML                                                    */
/* ------------------------------------------------------------------ */

function reportHtmlFor(projectId: string): string {
  const project = findProject(projectId);
  const timeline = timelines[projectId];
  const rows = (timeline?.segments ?? [])
    .map(
      (s) =>
        `<tr><td>${s.start.toFixed(2)}s</td><td>${s.stop.toFixed(2)}s</td><td><span class="tag ${s.label}">${s.label}</span></td><td>${(s.confidence * 100).toFixed(0)}%</td></tr>`,
    )
    .join("");
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>${project.name} · 分析报告</title>
<style>
body{margin:0;background:#0b0e14;color:#e6edf7;font:14px/1.6 "Segoe UI","Microsoft YaHei UI",system-ui,sans-serif;padding:28px 32px}
h1{font-size:22px;margin:0 0 4px}.muted{color:#8b9bb4}.card{background:#121722;border:1px solid #263041;border-radius:12px;padding:18px 20px;margin:16px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.k{color:#8b9bb4;font-size:12px}.v{font-size:20px;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid #263041}
th{color:#8b9bb4;font-weight:500}
.tag{padding:1px 8px;border-radius:999px;font-size:12px}
.vocals{background:rgba(96,165,250,.18);color:#60a5fa}.music{background:rgba(52,211,153,.18);color:#34d399}
.vocals\\+music{background:rgba(167,139,250,.18);color:#a78bfa}.other{background:rgba(148,163,184,.18);color:#94a3b8}
.bar{height:8px;border-radius:999px;background:#171e2b;overflow:hidden;display:flex}
.bar span{display:block;height:100%}
</style></head><body>
<h1>${project.name}</h1><div class="muted">AudioLab Studio 分析报告 · ${new Date().toLocaleString("zh-CN")} · 演示数据</div>
<div class="card"><div class="grid">
<div><div class="k">时长</div><div class="v">${(project.media?.duration ?? 0).toFixed(1)}s</div></div>
<div><div class="k">采样率</div><div class="v">${((project.media?.sample_rate ?? 0) / 1000).toFixed(1)} kHz</div></div>
<div><div class="k">人声</div><div class="v">${Number(project.summary.vocals ?? 0).toFixed(1)}s</div></div>
<div><div class="k">音乐</div><div class="v">${Number(project.summary.music ?? 0).toFixed(1)}s</div></div>
<div><div class="k">音色簇</div><div class="v">${project.summary.clusters ?? 0}</div></div>
<div><div class="k">整体响度</div><div class="v">${project.summary.integrated_lufs ?? "—"} LUFS</div></div>
</div></div>
<div class="card"><h3 style="margin:0 0 12px">标签时长占比</h3>
<div class="bar"><span style="width:46.9%;background:#60a5fa"></span><span style="width:21.1%;background:#34d399"></span><span style="width:19%;background:#a78bfa"></span><span style="width:12.9%;background:#94a3b8"></span></div></div>
<div class="card"><h3 style="margin:0 0 8px">分段明细</h3>
<table><thead><tr><th>开始</th><th>结束</th><th>标签</th><th>置信度</th></tr></thead><tbody>${rows}</tbody></table></div>
</body></html>`;
}

/* ------------------------------------------------------------------ */
/* Client implementation                                               */
/* ------------------------------------------------------------------ */

export function createDemoClient(): ApiClient {
  startLiveTick();
  return {
    demo: true,

    async health() {
      return clone(health);
    },
    async doctor() {
      return clone(doctor);
    },

    async listProjects(params = {}) {
      let items = projects.slice();
      const query = (params.query ?? "").trim().toLowerCase();
      if (query) {
        items = items.filter(
          (p) =>
            p.name.toLowerCase().includes(query) ||
            p.source_path.toLowerCase().includes(query) ||
            p.tags.some((t) => t.toLowerCase().includes(query)),
        );
      }
      if (params.status) items = items.filter((p) => p.status === params.status);
      const page = params.page ?? 1;
      const pageSize = params.page_size ?? 50;
      const paged: PagedProjects = {
        items: clone(items.slice((page - 1) * pageSize, page * pageSize)),
        total: items.length,
        page,
      };
      return paged;
    },

    async importPaths(paths) {
      const created: Project[] = [];
      const errors: string[] = [];
      for (const path of paths) {
        const filename = path.split(/[\\/]/).pop() ?? path;
        if (!/\.(mp3|wav|flac|m4a|aac|ogg|opus|wma|aiff?|mp4|mov|mkv|webm|avi)$/i.test(filename)) {
          errors.push(`不支持的文件类型：${filename}`);
          continue;
        }
        const id = `p-${Date.now().toString(36)}-${created.length}`;
        const project: Project = {
          id,
          name: filename.replace(/\.[^.]+$/, ""),
          source_path: path,
          status: "imported",
          media: media({ filename, duration: 24.8 }),
          tags: ["演示导入"],
          summary: { duration: 24.8 },
          result_dir: `E:\\AudioLab\\workspace\\${id}`,
          created_at: now(),
          updated_at: now(),
          error: "",
        };
        projects.unshift(project);
        created.push(project);
        emit({ type: "project", project: clone(project) });
      }
      return { projects: clone(created), errors } satisfies ImportResult;
    },

    async uploadFiles(files) {
      return this.importPaths(files.map((f) => `C:\\fakepath\\${f.name}`));
    },

    async getProject(id) {
      return clone(findProject(id));
    },

    async patchProject(id, patch) {
      const project = findProject(id);
      if (patch.name) project.name = patch.name;
      if (patch.tags) project.tags = patch.tags.slice();
      project.updated_at = now();
      emit({ type: "project", project: clone(project) });
      return clone(project);
    },

    async deleteProject(id) {
      const index = projects.findIndex((p) => p.id === id);
      if (index >= 0) projects.splice(index, 1);
      delete timelines[id];
      delete timbres[id];
      delete artifacts[id];
      return { ok: true };
    },

    async analyze(id) {
      const project = findProject(id);
      const job = startAnalyzeJob(project);
      return { job_id: job.id } satisfies JobSummary;
    },

    async refuse(id) {
      const project = findProject(id);
      const job = startRefuseJob(project);
      return { job_id: job.id } satisfies JobSummary;
    },

    async process(id, opts) {
      const project = findProject(id);
      const job = startProcessJob(project, opts);
      return { job_id: job.id } satisfies JobSummary;
    },

    async timeline(id) {
      findProject(id);
      const timeline = timelines[id];
      if (!timeline) throw new Error("该项目尚未分析完成，暂无时间轴数据。请先点击「一键分析」。");
      return clone(timeline);
    },

    async timbre(id) {
      findProject(id);
      const timbre = timbres[id];
      if (!timbre) throw new Error("该项目尚未生成音色聚类，请先完成分析。");
      return clone(timbre);
    },

    async artifacts(id) {
      findProject(id);
      return { artifacts: clone(artifacts[id] ?? []) };
    },

    async peaks(id, artifactId) {
      const project = findProject(id);
      const duration = project.media?.duration ?? 29.4;
      const seed = (artifactId.length % 7) + project.id.length;
      return makePeaks(duration, seed);
    },

    async setSegmentLabel(id, segmentId, userLabel) {
      const timeline = timelines[id];
      if (!timeline) throw new Error("暂无时间轴数据");
      const targetIndex = timeline.segments.findIndex((segment) => segment.id === segmentId);
      const index = targetIndex >= 0 ? targetIndex : segmentId;
      const segment = timeline.segments[index];
      if (!segment) throw new Error(`分段不存在：${segmentId}`);
      segment.user_label = userLabel;
      if (userLabel) segment.label = userLabel as Timeline["segments"][number]["label"];
      timeline.summary = summarize(timeline.segments);
      return clone(timeline);
    },

    async mergeSegments(id, segmentIds) {
      const timeline = timelines[id];
      if (!timeline) throw new Error("暂无时间轴数据");
      const indices = Array.from(
        new Set(
          segmentIds.map((segmentId) => {
            const found = timeline.segments.findIndex((segment) => segment.id === segmentId);
            return found >= 0 ? found : segmentId;
          }),
        ),
      ).sort((a, b) => a - b);
      if (indices.length < 2) throw new Error("请选择至少两个相邻分段");
      const selected = indices.map((i) => timeline.segments[i]).filter(Boolean);
      const start = Math.min(...selected.map((s) => s.start));
      const stop = Math.max(...selected.map((s) => s.stop));
      const labels = new Map<string, number>();
      for (const s of selected) labels.set(s.label, (labels.get(s.label) ?? 0) + (s.stop - s.start));
      let best: Timeline["segments"][number]["label"] = selected[0].label;
      let bestTime = -1;
      labels.forEach((seconds, label) => {
        if (seconds > bestTime) {
          bestTime = seconds;
          best = label as Timeline["segments"][number]["label"];
        }
      });
      const merged = {
        id: selected[0].id,
        start,
        stop,
        label: best,
        confidence: Math.max(...selected.map((s) => s.confidence)),
        tags: selected.reduce<Record<string, number>>((acc, s) => {
          for (const [k, v] of Object.entries(s.tags)) acc[k] = Math.max(acc[k] ?? 0, v);
          return acc;
        }, {}),
        user_label: null,
      };
      const first = indices[0];
      const rest = new Set(indices.slice(1));
      timeline.segments = timeline.segments
        .map((s, i) => (i === first ? merged : s))
        .filter((_, i) => !rest.has(i));
      timeline.summary = summarize(timeline.segments);
      return clone(timeline);
    },

    async splitSegment(id, segmentId, at) {
      const timeline = timelines[id];
      if (!timeline) throw new Error("暂无时间轴数据");
      const targetIndex = timeline.segments.findIndex((segment) => segment.id === segmentId);
      const index = targetIndex >= 0 ? targetIndex : segmentId;
      const segment = timeline.segments[index];
      if (!segment) throw new Error(`分段不存在：${segmentId}`);
      if (at <= segment.start + 0.05 || at >= segment.stop - 0.05) {
        throw new Error("切分点需落在分段内部（至少距边缘 50ms）");
      }
      const maxId = Math.max(...timeline.segments.map((s) => s.id ?? 0), 0);
      const left = { ...segment, stop: Number(at.toFixed(3)) };
      const right = { ...segment, id: maxId + 1, start: Number(at.toFixed(3)) };
      timeline.segments = [
        ...timeline.segments.slice(0, index),
        left,
        right,
        ...timeline.segments.slice(index + 1),
      ];
      timeline.summary = summarize(timeline.segments);
      return clone(timeline);
    },

    async setClusterLabel(clusterId, userLabel) {
      const { projectId, cluster } = findCluster(clusterId);
      cluster.user_label = userLabel;
      if (userLabel) cluster.label = userLabel;
      return clone(timbres[projectId]);
    },

    async mergeClusters(id, clusterIds) {
      const timbre = timbres[id];
      if (!timbre) throw new Error("暂无音色数据");
      const clusters = timbre.clusters.filter((c) => clusterIds.includes(c.id));
      if (clusters.length < 2) throw new Error("请选择至少两个音色簇");
      const target = clusters[0];
      for (const c of clusters.slice(1)) {
        target.clips = [...target.clips, ...c.clips];
        target.n_clips = target.clips.length;
        target.total_duration = Number(
          (target.total_duration + c.total_duration).toFixed(2),
        );
      }
      const mergedIds = new Set(clusters.slice(1).map((c) => c.id));
      timbre.clusters = timbre.clusters.filter((c) => !mergedIds.has(c.id));
      return clone(timbre);
    },

    async listJobs(active) {
      const items = active ? jobs.filter((j) => j.status === "running" || j.status === "queued") : jobs;
      return { items: clone(items) };
    },

    async cancelJob(id) {
      const job = jobs.find((j) => j.id === id);
      if (!job) throw new Error(`任务不存在：${id}`);
      job.status = "canceled";
      job.stage = "已取消";
      job.finished_at = now();
      job.message = "用户取消";
      stopTimer(id);
      emitJob(job);
      return { ok: true };
    },

    async retryJob(id) {
      const job = jobs.find((j) => j.id === id);
      if (!job) throw new Error(`任务不存在：${id}`);
      if (job.kind === "analyze") {
        const project = findProject(job.project_id);
        const next = startAnalyzeJob(project);
        return { job_id: next.id };
      }
      if (job.kind === "process") {
        const project = findProject(job.project_id);
        const next = startProcessJob(project, {
          preset: (job.params.preset as ProcessOptions["preset"]) ?? "douyin",
        });
        return { job_id: next.id };
      }
      const model = models.find((m) => m.id === job.params.model_id);
      if (!model) throw new Error("无法重试：模型不存在");
      const next = startDownloadJob(model);
      return { job_id: next.id };
    },

    async jobLog(id) {
      return { lines: clone(logs[id] ?? ["[demo] 暂无日志"]) };
    },

    async listModels() {
      return { models: clone(models) };
    },

    async downloadModel(id) {
      const model = models.find((m) => m.id === id);
      if (!model) throw new Error(`模型不存在：${id}`);
      if (model.status === "ready") throw new Error(`${model.label} 已就绪，无需下载`);
      const job = startDownloadJob(model);
      return { job_id: job.id };
    },

    async deleteModel(id) {
      const model = models.find((m) => m.id === id);
      if (!model) throw new Error(`模型不存在：${id}`);
      model.status = "missing";
      model.path = "";
      emit({ type: "model", model: clone(model) });
      return { ok: true };
    },

    async getSettings() {
      return clone(settings);
    },

    async patchSettings(patch) {
      Object.assign(settings, patch);
      return clone(settings);
    },

    subscribe(handler) {
      listeners.add(handler);
      return () => listeners.delete(handler);
    },

    reportUrl(id) {
      return `/api/projects/${encodeURIComponent(id)}/report`;
    },
    exportUrl() {
      return "";
    },
    fileUrl(id, relPath) {
      return `/api/files/${encodeURIComponent(id)}/${relPath}`;
    },
    reportHtml(id) {
      try {
        findProject(id);
        return reportHtmlFor(id);
      } catch {
        return null;
      }
    },
  };
}

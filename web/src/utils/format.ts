/** Formatting helpers shared by every panel. */
import type { JobStatus, Label, ProjectStatus } from "../api/types";

export const LABEL_TEXT: Record<Label, string> = {
  vocals: "人声",
  music: "音乐",
  "vocals+music": "混合",
  other: "其他",
};

export const LABEL_COLOR: Record<Label, string> = {
  vocals: "var(--vocals)",
  music: "var(--music)",
  "vocals+music": "var(--mixed)",
  other: "var(--other)",
};

export const LABEL_HEX: Record<Label, string> = {
  vocals: "#60a5fa",
  music: "#34d399",
  "vocals+music": "#a78bfa",
  other: "#94a3b8",
};

export const STATUS_TEXT: Record<ProjectStatus, string> = {
  imported: "已导入",
  analyzing: "分析中",
  analyzed: "已分析",
  processing: "处理中",
  ready: "已就绪",
  error: "出错",
};

export const STATUS_COLOR: Record<ProjectStatus, string> = {
  imported: "var(--muted)",
  analyzing: "var(--accent-2)",
  analyzed: "var(--accent)",
  processing: "var(--warn)",
  ready: "var(--music)",
  error: "var(--danger)",
};

export const JOB_STATUS_TEXT: Record<JobStatus, string> = {
  queued: "等待中",
  running: "运行中",
  done: "已完成",
  failed: "失败",
  canceled: "已取消",
  interrupted: "已中断",
};

export const JOB_KIND_TEXT: Record<string, string> = {
  analyze: "分析",
  refuse: "重新融合",
  process: "处理",
  download: "下载模型",
};

/** Backend job stages are English slugs; show Chinese labels in the UI. */
export const JOB_STAGE_TEXT: Record<string, string> = {
  queued: "排队中",
  prepare: "准备中",
  init: "初始化",
  probe: "媒体探测",
  extract: "音频提取",
  media: "媒体探测",
  separation: "人声分离",
  separate: "人声分离",
  vad: "语音检测",
  segment: "分段",
  tagging: "AST 标签",
  tag: "AST 标签",
  fusion: "证据融合",
  timbre: "音色聚类",
  cluster: "音色聚类",
  preview: "生成预览",
  report: "生成报告",
  done: "完成",
  cancel: "已取消",
  canceled: "已取消",
  failed: "失败",
  denoise: "降噪",
  loudnorm: "响度归一",
  duck: "侧链闪避",
  mux: "视频回封",
  encode: "编码输出",
  download: "下载模型",
  verify: "校验模型",
  load: "加载模型",
  load_model: "加载模型",
  process: "处理",
  processing: "处理中",
  mix: "混音",
  polish: "母带处理",
  refuse: "重新融合",
  refusal: "重新融合",
  analyze: "分析",
  analysing: "分析中",
  analyzing: "分析中",
  enriched: "标签补全",
  cleanup: "清理缓存",
  finalize: "收尾",
  interrupted: "已中断",
  cancelled: "已取消",
};

/** Map an English job stage (or "stage:detail") to a Chinese label. */
export function stageText(stage: string): string {
  if (!stage) return "";
  const normalized = stage.trim().toLowerCase();
  if (JOB_STAGE_TEXT[normalized]) return JOB_STAGE_TEXT[normalized];
  const base = normalized.split(/[:\s/]/)[0];
  return JOB_STAGE_TEXT[base] ?? stage;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** 0:29.4 — used on the timeline / transport. */
export function formatSeconds(seconds: number, showTenths = true): string {
  if (!Number.isFinite(seconds) || seconds < 0) seconds = 0;
  const tenths = Math.round(seconds * 10);
  const whole = Math.floor(tenths / 10);
  const tenth = tenths % 10;
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  const s = whole % 60;
  const base = h > 0 ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
  return showTenths && h === 0 ? `${base}.${tenth}` : base;
}

/** Human summary: 29.4 秒 / 2 分 13 秒 / 1 小时 02 分 */
export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0 秒";
  if (seconds < 60) return `${seconds.toFixed(1)} 秒`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m < 60) return `${m} 分 ${String(s).padStart(2, "0")} 秒`;
  const h = Math.floor(m / 60);
  return `${h} 小时 ${String(m % 60).padStart(2, "0")} 分`;
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let idx = 0;
  let value = bytes;
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024;
    idx += 1;
  }
  return `${value >= 100 ? value.toFixed(0) : value.toFixed(1)} ${units[idx]}`;
}

export function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toFixed(digits);
}

export function percent(value: number, digits = 0): string {
  return `${(clamp(value, 0, 1) * 100).toFixed(digits)}%`;
}

/**
 * The backend may report job progress either as 0..1 or 0..100.
 * Normalise to 0..1 so every progress bar behaves the same.
 */
export function normalizeProgress(value: number | null | undefined): number {
  if (value === null || value === undefined || !Number.isFinite(value)) return 0;
  const ratio = value > 1 ? value / 100 : value;
  return clamp(ratio, 0, 1);
}

export function relativeTime(iso: string): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const diff = Date.now() - then;
  if (diff < 0) return "刚刚";
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} 天前`;
  return new Date(iso).toLocaleDateString("zh-CN");
}

export function elapsedTime(startIso: string, endIso: string): string {
  if (!startIso) return "—";
  const start = new Date(startIso).getTime();
  const end = endIso ? new Date(endIso).getTime() : Date.now();
  if (Number.isNaN(start) || Number.isNaN(end)) return "—";
  const seconds = Math.max(0, (end - start) / 1000);
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  if (minutes < 60) return `${minutes}m ${String(rest).padStart(2, "0")}s`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}

export function shortHash(sha: string): string {
  if (!sha) return "—";
  return sha.length > 12 ? `${sha.slice(0, 12)}…` : sha;
}

export function effectiveLabel(segment: { label: Label; user_label?: string | null }): Label {
  const user = segment.user_label;
  if (user === "vocals" || user === "music" || user === "vocals+music" || user === "other") {
    return user;
  }
  return segment.label;
}

export function topTags(tags: Record<string, number>, count = 2): string[] {
  return Object.entries(tags)
    .sort((a, b) => b[1] - a[1])
    .slice(0, count)
    .map(([name]) => name);
}

export function friendlyError(raw: string): string {
  const text = raw || "未知错误";
  if (/Failed to fetch|NetworkError|ERR_CONNECTION/i.test(text)) {
    return "无法连接后端，请确认 AudioLab 后端已启动（默认 127.0.0.1:7861）。";
  }
  return text;
}

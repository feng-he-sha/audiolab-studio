/**
 * The single place where the frontend talks to the AudioLab backend.
 * Every fetch/WebSocket lives here; components only call these methods.
 */
import type {
  AnalyzeOptions,
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
  Preset,
  ProcessOptions,
  Project,
  RefuseOptions,
  ServerEvent,
  Settings,
  Timeline,
  TimbreResult,
  TranscriptResult,
} from "./types";
import { createDemoClient, demoEnabled } from "./demo";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "") continue;
    sp.set(key, String(value));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

function errorHint(status: number, detail: string): string {
  if (status === 0) return "无法连接后端，请确认 AudioLab 后端已启动（默认 127.0.0.1:7861）。";
  if (status === 404) return `接口或资源不存在：${detail || "404"}`;
  if (status === 409) return `当前状态冲突：${detail || "任务正在进行"}`;
  if (status === 422) return `参数校验失败：${detail || "请检查输入"}`;
  if (status >= 500) return `后端内部错误：${detail || `HTTP ${status}`}`;
  return detail || `请求失败（HTTP ${status}）`;
}

async function parseError(res: Response): Promise<string> {
  try {
    const data: unknown = await res.json();
    if (data && typeof data === "object") {
      const obj = data as Record<string, unknown>;
      if (typeof obj.detail === "string") return obj.detail;
      if (Array.isArray(obj.detail)) return JSON.stringify(obj.detail);
      if (typeof obj.error === "string") return obj.error;
      if (typeof obj.message === "string") return obj.message;
    }
    return JSON.stringify(data);
  } catch {
    return res.statusText;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    throw new ApiError(0, `无法连接后端（${msg}）。请确认后端已启动后重试。`);
  }
  if (!res.ok) {
    const detail = await parseError(res);
    throw new ApiError(res.status, errorHint(res.status, detail));
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(res.status, "后端返回了非 JSON 数据，请检查接口实现。");
  }
}

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

function wsUrl(): string {
  const base = API_BASE && /^https?:/i.test(API_BASE) ? API_BASE : window.location.origin;
  const url = new URL("/api/ws/events", base);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

const enc = encodeURIComponent;

/* ------------------------------------------------------------------ */
/* Real implementation                                                 */
/* ------------------------------------------------------------------ */

const realClient: ApiClient = {
  demo: false,

  health: () => request<Health>("/api/health"),
  doctor: () => request<DoctorResult>("/api/doctor"),

  listProjects: (params = {}) =>
    request<PagedProjects>(`/api/projects${qs({ ...params })}`),

  importPaths: (paths) =>
    request<ImportResult>("/api/projects/import", jsonInit("POST", { paths })),

  uploadFiles: (files) => {
    const form = new FormData();
    for (const file of files) form.append("files", file, file.name);
    return request<ImportResult>("/api/projects/upload", { method: "POST", body: form });
  },

  getProject: (id) => request<Project>(`/api/projects/${enc(id)}`),

  patchProject: (id, patch) =>
    request<Project>(`/api/projects/${enc(id)}`, jsonInit("PATCH", patch)),

  deleteProject: (id, deleteOutputs = true) =>
    request<{ ok: boolean }>(
      `/api/projects/${enc(id)}${qs({ delete_outputs: deleteOutputs })}`,
      { method: "DELETE" },
    ),

  analyze: (id, opts: AnalyzeOptions = {}) =>
    request<JobSummary>(`/api/projects/${enc(id)}/analyze`, jsonInit("POST", opts)),

  refuse: (id, opts: RefuseOptions = {}) =>
    request<JobSummary>(`/api/projects/${enc(id)}/refuse`, jsonInit("POST", opts)),

  process: (id, opts: ProcessOptions) =>
    request<JobSummary>(`/api/projects/${enc(id)}/process`, jsonInit("POST", opts)),

  timeline: (id) => request<Timeline>(`/api/projects/${enc(id)}/timeline`),
  timbre: (id) => request<TimbreResult>(`/api/projects/${enc(id)}/timbre`),
  artifacts: (id) =>
    request<{ artifacts: Artifact[] }>(`/api/projects/${enc(id)}/artifacts`),
  peaks: (id, artifactId) =>
    request<Peaks>(`/api/projects/${enc(id)}/peaks/${enc(artifactId)}`),
  transcript: (id) =>
    request<TranscriptResult>(`/api/projects/${enc(id)}/transcript`),

  setSegmentLabel: (id, segmentId, userLabel) =>
    request<Timeline>(
      `/api/projects/${enc(id)}/segments/${segmentId}`,
      jsonInit("PATCH", { user_label: userLabel }),
    ),
  mergeSegments: (id, segmentIds) =>
    request<Timeline>(
      `/api/projects/${enc(id)}/segments/merge`,
      jsonInit("POST", { segment_ids: segmentIds }),
    ),
  splitSegment: (id, segmentId, at) =>
    request<Timeline>(
      `/api/projects/${enc(id)}/segments/split`,
      jsonInit("POST", { segment_id: segmentId, at }),
    ),
  setClusterLabel: (clusterId, userLabel) =>
    request<TimbreResult>(
      `/api/clusters/${enc(clusterId)}`,
      jsonInit("PATCH", { user_label: userLabel }),
    ),
  mergeClusters: (id, clusterIds) =>
    request<TimbreResult>(
      `/api/projects/${enc(id)}/clusters/merge`,
      jsonInit("POST", { cluster_ids: clusterIds }),
    ),

  listJobs: (active) =>
    request<{ items: Job[] }>(`/api/jobs${qs({ active: active === true ? true : undefined })}`),
  cancelJob: (id) =>
    request<{ ok: boolean }>(`/api/jobs/${enc(id)}/cancel`, { method: "POST" }),
  retryJob: (id) =>
    request<JobSummary>(`/api/jobs/${enc(id)}/retry`, { method: "POST" }),
  jobLog: (id) => request<{ lines: string[] }>(`/api/jobs/${enc(id)}/log`),

  listModels: () => request<{ models: ModelInfo[] }>("/api/models"),
  downloadModel: (id) =>
    request<JobSummary>(`/api/models/${enc(id)}/download`, { method: "POST" }),
  deleteModel: (id) =>
    request<{ ok: boolean }>(`/api/models/${enc(id)}`, { method: "DELETE" }),

  getSettings: () => request<Settings>("/api/settings"),
  patchSettings: (patch) => request<Settings>("/api/settings", jsonInit("PATCH", patch)),

  subscribe: (handler) => {
    let closed = false;
    let socket: WebSocket | null = null;
    let retry = 0;
    let reconnectTimer: number | null = null;
    let pingTimer: number | null = null;

    const connect = () => {
      if (closed) return;
      try {
        socket = new WebSocket(wsUrl());
      } catch {
        scheduleReconnect();
        return;
      }
      socket.onopen = () => {
        retry = 0;
        pingTimer = window.setInterval(() => {
          try {
            socket?.send(JSON.stringify({ type: "ping" }));
          } catch {
            /* ignore */
          }
        }, 25000);
      };
      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(String(event.data)) as ServerEvent;
          if (data && typeof data === "object" && "type" in data) handler(data);
        } catch {
          /* ignore malformed frames */
        }
      };
      socket.onclose = () => {
        if (pingTimer !== null) {
          window.clearInterval(pingTimer);
          pingTimer = null;
        }
        scheduleReconnect();
      };
      socket.onerror = () => {
        try {
          socket?.close();
        } catch {
          /* ignore */
        }
      };
    };

    const scheduleReconnect = () => {
      if (closed) return;
      retry += 1;
      const delay = Math.min(15000, 1200 * retry);
      reconnectTimer = window.setTimeout(connect, delay);
    };

    connect();

    return () => {
      closed = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      if (pingTimer !== null) window.clearInterval(pingTimer);
      if (socket) {
        socket.onclose = null;
        try {
          socket.close();
        } catch {
          /* ignore */
        }
      }
    };
  },

  reportUrl: (id) => `${API_BASE}/api/projects/${enc(id)}/report`,
  exportUrl: (id, format) =>
    `${API_BASE}/api/projects/${enc(id)}/export${qs({ format })}`,
  transcriptExportUrl: (id, format) =>
    `${API_BASE}/api/projects/${enc(id)}/transcript/export${qs({ format })}`,
  fileUrl: (id, relPath) => `${API_BASE}/api/files/${enc(id)}/${relPath}`,
  reportHtml: () => null,
};

/* ------------------------------------------------------------------ */
/* Client selection                                                    */
/* ------------------------------------------------------------------ */

let cached: ApiClient | null = null;

export function getClient(): ApiClient {
  if (cached) return cached;
  cached = demoEnabled() ? createDemoClient() : realClient;
  return cached;
}

export function isDemoMode(): boolean {
  return getClient().demo;
}

/** Human readable helper reused by error toasts. */
export function describeError(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message || String(err);
  return String(err);
}

export type { Preset };

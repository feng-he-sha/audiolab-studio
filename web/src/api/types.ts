/**
 * AudioLab Studio — shared API types.
 * Mirrors docs/API_CONTRACT.md (snake_case payloads) and
 * src/audiolab/core/schemas.py.
 */

export type Label = "vocals" | "music" | "vocals+music" | "other";

export type ProjectStatus =
  | "imported"
  | "analyzing"
  | "analyzed"
  | "processing"
  | "ready"
  | "error";

export type Preset = "douyin" | "podcast" | "movie" | "music" | "clean";
export type Quality = "fast" | "balanced" | "hq";
export type DeviceTarget = "auto" | "cuda" | "cpu";
export type ThemeName = "dark" | "light";

export interface MediaInfo {
  path: string;
  filename: string;
  duration: number;
  sample_rate: number;
  channels: number;
  codec: string;
  bit_rate: number;
  size: number;
  sha256: string;
  has_video: boolean;
  video_width?: number | null;
  video_height?: number | null;
  has_audio: boolean;
  audio_track: number;
}

export interface Project {
  id: string;
  name: string;
  source_path: string;
  status: ProjectStatus;
  media?: MediaInfo | null;
  tags: string[];
  summary: Record<string, unknown>;
  result_dir: string;
  created_at: string;
  updated_at: string;
  error: string;
}

export interface Segment {
  /** Database row id (required by the real backend for edits). */
  id?: number;
  start: number;
  stop: number;
  label: Label;
  confidence: number;
  tags: Record<string, number>;
  user_label?: string | null;
}

export interface Timeline {
  duration: number;
  frame_hop: number;
  segments: Segment[];
  summary: Record<string, number>;
  warnings: string[];
}

export interface TimbreFeatures {
  f0_median?: number | null;
  f0_mean?: number | null;
  f0_std?: number | null;
  voiced_ratio: number;
  centroid_mean: number;
  centroid_std: number;
  rolloff_mean: number;
  flatness_mean: number;
  zcr_mean: number;
  harmonic_ratio: number;
  rms_db: number;
  duration: number;
}

export interface TimbreClip {
  id: string;
  path: string;
  url: string;
  start: number;
  stop: number;
  duration: number;
  cluster: number;
  features: TimbreFeatures;
  is_representative: boolean;
}

export interface TimbreCluster {
  id: string;
  index: number;
  label: string;
  color: string;
  n_clips: number;
  total_duration: number;
  features: TimbreFeatures;
  clips: TimbreClip[];
  representative: string[];
  user_label?: string | null;
}

export interface TimbrePoint {
  x: number;
  y: number;
  cluster: number;
  clip_id?: string;
}

export interface TimbreResult {
  backend: "colorsplitter" | "mfcc" | string;
  clusters: TimbreCluster[];
  points: TimbrePoint[];
  warnings: string[];
}

export type ArtifactKind =
  | "original"
  | "vocals"
  | "instrumental"
  | "processed"
  | "preview"
  | "report";

export interface Artifact {
  id: string;
  kind: ArtifactKind;
  label: string;
  path: string;
  url: string;
  duration: number;
  size: number;
  mime: string;
}

export type JobKind = "analyze" | "refuse" | "process" | "download" | string;
export type JobStatus =
  | "queued"
  | "running"
  | "done"
  | "failed"
  | "canceled"
  | "interrupted";

export interface Job {
  id: string;
  project_id: string;
  kind: JobKind;
  status: JobStatus;
  stage: string;
  progress: number;
  message: string;
  created_at: string;
  started_at: string;
  finished_at: string;
  error: string;
  params: Record<string, unknown>;
}

export interface EngineSpec {
  id: string;
  kind: string;
  label: string;
  version: string;
  license: string;
  description: string;
  model_ids: string[];
  capabilities: string[];
  params_schema: Record<string, unknown>;
}

export type ModelStatus = "missing" | "downloading" | "ready" | "error";

export interface ModelInfo {
  id: string;
  engine: string;
  filename: string;
  label: string;
  size: number;
  status: ModelStatus;
  path: string;
  license: string;
  source: string;
  sha256: string;
  error: string;
}

export interface Health {
  ok: boolean;
  version: string;
  device: string;
  cuda: boolean;
  ffmpeg: boolean;
  web?: boolean;
}

export interface DoctorCheck {
  name: string;
  ok: boolean;
  detail: string;
  hint: string;
}

export interface DoctorResult {
  ok: boolean;
  checks: DoctorCheck[];
}

export interface Settings {
  workspace_dir: string;
  models_dir: string;
  device: DeviceTarget;
  hf_endpoint: string;
  preview_quality: number;
  max_gpu_jobs: number;
  theme: ThemeName;
  language: string;
  auto_open_report: boolean;
}

export interface PagedProjects {
  items: Project[];
  total: number;
  page: number;
}

export interface ImportResult {
  projects: Project[];
  errors: string[];
}

export interface Peaks {
  duration: number;
  peaks: [number, number][];
}

export interface AnalyzeOptions {
  quality?: Quality;
  separation_model?: string;
  skip_tagging?: boolean;
  clusters?: number;
  timbre_threshold?: number;
  force?: boolean;
}

export interface RefuseOptions {
  min_segment?: number;
  smooth_frames?: number;
  min_music?: number;
}

export interface ProcessOptions {
  preset: Preset;
  params?: Record<string, unknown>;
  mux_video?: boolean;
  output_format?: string;
}

export interface JobSummary {
  job_id: string;
}

/* ------------------------------------------------------------------ */
/* Speech-to-text (SenseVoice)                                        */
/* ------------------------------------------------------------------ */

export type TranscriptFormat = "srt" | "vtt" | "txt";

export interface TranscriptSegment {
  id: number;
  start: number;
  stop: number;
  text: string;
  /** May be empty when the engine does not detect the language per segment. */
  language: string;
  /** May be empty: neutral | happy | sad | angry | surprise ... */
  emotion: string;
  /** May be empty: Speech | Music | Laughter | Applause ... */
  event: string;
}

export interface TranscriptResult {
  backend: "sensevoice" | string;
  model_dir: string;
  /** zh / en / ja / ko / yue / auto */
  language: string;
  text: string;
  duration: number;
  /** Backend decode time in seconds (optional for older payloads). */
  elapsed?: number;
  warnings: string[];
  segments: TranscriptSegment[];
}

/** WebSocket /api/ws/events payloads. */
export type ServerEvent =
  | { type: "job"; job: Job }
  | { type: "log"; job_id: string; line: string }
  | { type: "model"; model: ModelInfo }
  | { type: "project"; project: Project }
  | { type: "pong" };

export interface ApiClient {
  readonly demo: boolean;

  health(): Promise<Health>;
  doctor(): Promise<DoctorResult>;

  listProjects(params?: {
    query?: string;
    status?: string;
    page?: number;
    page_size?: number;
  }): Promise<PagedProjects>;
  importPaths(paths: string[]): Promise<ImportResult>;
  uploadFiles(files: File[]): Promise<ImportResult>;
  getProject(id: string): Promise<Project>;
  patchProject(id: string, patch: { name?: string; tags?: string[] }): Promise<Project>;
  deleteProject(id: string, deleteOutputs?: boolean): Promise<{ ok: boolean }>;

  analyze(id: string, opts?: AnalyzeOptions): Promise<JobSummary>;
  refuse(id: string, opts?: RefuseOptions): Promise<JobSummary>;
  process(id: string, opts: ProcessOptions): Promise<JobSummary>;

  timeline(id: string): Promise<Timeline>;
  timbre(id: string): Promise<TimbreResult>;
  artifacts(id: string): Promise<{ artifacts: Artifact[] }>;
  peaks(id: string, artifactId: string): Promise<Peaks>;
  transcript(id: string): Promise<TranscriptResult>;

  setSegmentLabel(
    id: string,
    segmentId: number,
    userLabel: string | null,
  ): Promise<Timeline>;
  mergeSegments(id: string, segmentIds: number[]): Promise<Timeline>;
  splitSegment(id: string, segmentId: number, at: number): Promise<Timeline>;
  setClusterLabel(clusterId: string, userLabel: string | null): Promise<TimbreResult>;
  mergeClusters(id: string, clusterIds: string[]): Promise<TimbreResult>;

  listJobs(active?: boolean): Promise<{ items: Job[] }>;
  cancelJob(id: string): Promise<{ ok: boolean }>;
  retryJob(id: string): Promise<JobSummary>;
  jobLog(id: string): Promise<{ lines: string[] }>;

  listModels(): Promise<{ models: ModelInfo[] }>;
  downloadModel(id: string): Promise<JobSummary>;
  deleteModel(id: string): Promise<{ ok: boolean }>;

  getSettings(): Promise<Settings>;
  patchSettings(patch: Partial<Settings>): Promise<Settings>;

  /** Subscribe to server-pushed events. Returns an unsubscribe callback. */
  subscribe(handler: (event: ServerEvent) => void): () => void;

  reportUrl(id: string): string;
  exportUrl(id: string, format: string): string;
  transcriptExportUrl(id: string, format: TranscriptFormat): string;
  fileUrl(id: string, relPath: string): string;
  /** Demo only: inline report HTML. Real backend returns null (use iframe). */
  reportHtml(id: string): string | null;
}

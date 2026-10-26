/** 概览 tab: media info, six analysis stages, label ratio, warnings, recent jobs. */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Circle,
  Clock,
  FileAudio,
  FileText,
  Gauge,
  Layers,
  Loader2,
  Music,
  RefreshCw,
  Sparkles,
  Tags,
  Wand2,
} from "lucide-react";
import { describeError } from "../api/client";
import type { Artifact, Job, Project, Timeline, TimbreResult } from "../api/types";
import { useStudio } from "../state/StudioContext";
import { useToast } from "../state/ui";
import {
  JOB_KIND_TEXT,
  JOB_STATUS_TEXT,
  LABEL_TEXT,
  STATUS_TEXT,
  formatBytes,
  formatDuration,
  formatNumber,
  relativeTime,
  shortHash,
  stageText,
} from "../utils/format";
import { Chip, EmptyState, LoadingBlock, ProgressBar, SectionTitle, StatusDot } from "./common/ui";

interface Stage {
  name: string;
  detail: string;
  done: boolean;
  running: boolean;
}

function deriveStages(
  project: Project,
  timeline: Timeline | null,
  timbre: TimbreResult | null,
  artifacts: Artifact[],
): Stage[] {
  const running = project.status === "analyzing" || project.status === "processing";
  const hasTags = Boolean(timeline?.segments.some((segment) => Object.keys(segment.tags).length > 0));
  const hasSeparation = artifacts.some(
    (item) => item.kind === "vocals" || item.kind === "instrumental",
  );
  return [
    {
      name: "导入项目",
      detail: project.media ? `已识别 ${project.media.filename}` : "等待媒体探测",
      done: Boolean(project.media),
      running: false,
    },
    {
      name: "媒体探测",
      detail: project.media
        ? `${formatDuration(project.media.duration)} · ${project.media.codec || "未知编码"} · ${project.media.sample_rate / 1000} kHz`
        : "读取容器/编码信息",
      done: Boolean(project.media),
      running: running && !project.media,
    },
    {
      name: "语音检测与分段",
      detail: timeline
        ? `${timeline.segments.length} 个分段 · 帧移 ${Math.round(timeline.frame_hop * 1000)}ms`
        : "Silero VAD + 能量回退",
      done: Boolean(timeline && timeline.segments.length > 0),
      running: running && !timeline,
    },
    {
      name: "AST 音频标签",
      detail: hasTags ? "已生成音频事件标签" : "未生成（可能跳过或模型缺失）",
      done: hasTags,
      running: running && Boolean(timeline) && !hasTags,
    },
    {
      name: "音色聚类",
      detail: timbre
        ? `${timbre.clusters.length} 个簇 · ${timbre.backend === "mfcc" ? "MFCC 回退" : "ColorSplitter"}`
        : "提取嵌入并聚类",
      done: Boolean(timbre && timbre.clusters.length > 0),
      running: running && Boolean(timeline) && !timbre,
    },
    {
      name: "分离与报告",
      detail: hasSeparation ? "人声/伴奏 stems 已生成" : "人声分离与 HTML 报告",
      done: hasSeparation,
      running: running && Boolean(timbre) && !hasSeparation,
    },
  ];
}

export function OverviewPanel(): ReactNode {
  const { client, selectedProject, settings, jobs, dataVersion, setSelectedTab, toast } = useStudio();
  const project = selectedProject;
  const projectId = project?.id ?? "";
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [timbre, setTimbre] = useState<TimbreResult | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError("");
    const [timelineResult, timbreResult, artifactsResult] = await Promise.allSettled([
      client.timeline(projectId),
      client.timbre(projectId),
      client.artifacts(projectId),
    ]);
    if (timelineResult.status === "fulfilled") setTimeline(timelineResult.value);
    else setTimeline(null);
    if (timbreResult.status === "fulfilled") setTimbre(timbreResult.value);
    else setTimbre(null);
    if (artifactsResult.status === "fulfilled") {
      setArtifacts(artifactsResult.value.artifacts);
      setError("");
    } else {
      setArtifacts([]);
      const reason = artifactsResult.reason;
      if (!(reason instanceof Error && /尚未|404/.test(reason.message))) {
        setError(describeError(reason));
      }
    }
    setLoading(false);
  }, [client, projectId]);

  useEffect(() => {
    void load();
  }, [load, dataVersion]);

  const projectJobs = useMemo(
    () =>
      jobs
        .filter((job) => job.project_id === projectId)
        .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
        .slice(0, 4),
    [jobs, projectId],
  );

  if (!project) {
    return <EmptyState title="未选择项目" description="在左侧项目库选择一个项目。" />;
  }

  const stages = deriveStages(project, timeline, timbre, artifacts);
  const completed = stages.filter((stage) => stage.done).length;
  const warnings = [...(timeline?.warnings ?? []), ...(timbre?.warnings ?? [])];
  const duration = project.media?.duration ?? timeline?.duration ?? 0;
  const labels = (["vocals", "music", "vocals+music", "other"] as const).map((label) => ({
    label,
    seconds: Number(timeline?.summary?.[label] ?? project.summary?.[label] ?? 0),
  }));
  const totalLabeled = labels.reduce((sum, item) => sum + item.seconds, 0);
  const preset = typeof project.summary?.preset === "string" ? project.summary.preset : "";

  return (
    <div className="overview-panel">
      <div className="overview-hero">
        <div className="overview-hero-main">
          <div className="overview-title-row">
            <StatusDot status={project.status} />
            <h2>{project.name}</h2>
            <Chip tone="var(--muted)">{STATUS_TEXT[project.status] ?? project.status}</Chip>
            {preset ? <Chip tone="var(--accent)">预设 {preset}</Chip> : null}
          </div>
          <div className="overview-sub">
            <span>
              <FileAudio size={13} /> {project.media?.filename ?? project.source_path}
            </span>
            <span>
              <Clock size={13} /> 更新于 {relativeTime(project.updated_at)}
            </span>
            <span>
              <Gauge size={13} /> {completed}/6 阶段完成
            </span>
          </div>
          <div className="overview-progress">
            <ProgressBar value={completed / 6} tone="var(--accent)" />
          </div>
          <div className="overview-actions">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => {
                setSelectedTab("timeline");
              }}
            >
              <Activity size={14} /> 查看时间轴
            </button>
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => setSelectedTab("report")}
              disabled={artifacts.length === 0}
            >
              <FileText size={14} /> 分析报告
            </button>
            <button type="button" className="btn btn-sm" onClick={() => void load()}>
              <RefreshCw size={13} /> 刷新
            </button>
          </div>
        </div>
        <div className="overview-stats">
          <div className="overview-stat">
            <span className="k">时长</span>
            <span className="v">{formatDuration(duration)}</span>
          </div>
          <div className="overview-stat">
            <span className="k">音色簇</span>
            <span className="v">
              {timbre
                ? timbre.clusters.length
                : project.summary?.clusters !== undefined
                  ? Number(project.summary.clusters)
                  : "—"}
            </span>
          </div>
          <div className="overview-stat">
            <span className="k">整体响度</span>
            <span className="v">
              {project.summary?.integrated_lufs !== undefined
                ? `${formatNumber(Number(project.summary.integrated_lufs))} LUFS`
                : "—"}
            </span>
          </div>
          <div className="overview-stat">
            <span className="k">分段</span>
            <span className="v">{timeline?.segments.length ?? "—"}</span>
          </div>
        </div>
      </div>

      {project.error ? (
        <div className="banner banner-danger">
          <AlertTriangle size={15} /> {project.error}
        </div>
      ) : null}
      {error ? (
        <div className="banner banner-warn">
          <AlertTriangle size={15} /> {error}
          <button type="button" className="link-btn" onClick={() => void load()}>
            重试
          </button>
        </div>
      ) : null}

      <div className="overview-columns">
        <div className="card">
          <SectionTitle icon={<Layers size={15} />} title="分析阶段" extra={`${completed}/6`} />
          {loading && !timeline ? (
            <LoadingBlock rows={4} />
          ) : (
            <ul className="stage-list">
              {stages.map((stage) => (
                <li key={stage.name} className={`stage${stage.done ? " done" : ""}${stage.running ? " running" : ""}`}>
                  <span className="stage-icon">
                    {stage.running ? (
                      <Loader2 size={15} className="spin" />
                    ) : stage.done ? (
                      <CheckCircle2 size={15} />
                    ) : (
                      <Circle size={15} />
                    )}
                  </span>
                  <span className="stage-main">
                    <span className="stage-name">{stage.name}</span>
                    <span className="stage-detail">{stage.detail}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card">
          <SectionTitle icon={<Music size={15} />} title="标签时长占比" extra={formatDuration(totalLabeled)} />
          <div className="ratio-bar">
            {labels.map((item) =>
              item.seconds > 0 ? (
                <span
                  key={item.label}
                  className={`ratio-segment label-${item.label}`}
                  style={{ width: `${Math.max(1, (item.seconds / Math.max(0.001, totalLabeled)) * 100)}%` }}
                  title={`${LABEL_TEXT[item.label]} ${item.seconds.toFixed(1)}s`}
                />
              ) : null,
            )}
          </div>
          <div className="ratio-legend">
            {labels.map((item) => (
              <div className="ratio-legend-row" key={item.label}>
                <span className={`legend-dot label-${item.label}`} />
                <span className="legend-name">{LABEL_TEXT[item.label]}</span>
                <span className="legend-value">
                  {item.seconds.toFixed(1)}s ·{" "}
                  {totalLabeled > 0 ? Math.round((item.seconds / totalLabeled) * 100) : 0}%
                </span>
              </div>
            ))}
          </div>
          <div className="overview-tags">
            {project.tags.map((tag) => (
              <Chip key={tag}>{tag}</Chip>
            ))}
            {project.tags.length === 0 ? <span className="muted">暂无标签</span> : null}
          </div>
        </div>
      </div>

      <div className="overview-columns">
        <div className="card">
          <SectionTitle icon={<Tags size={15} />} title="媒体信息" />
          <dl className="kv-grid">
            <div>
              <dt>文件名</dt>
              <dd title={project.media?.path}>{project.media?.filename ?? "—"}</dd>
            </div>
            <div>
              <dt>编码</dt>
              <dd>{project.media?.codec || "—"}</dd>
            </div>
            <div>
              <dt>采样率</dt>
              <dd>{project.media ? `${project.media.sample_rate} Hz` : "—"}</dd>
            </div>
            <div>
              <dt>声道</dt>
              <dd>{project.media?.channels ?? "—"}</dd>
            </div>
            <div>
              <dt>码率</dt>
              <dd>{project.media?.bit_rate ? `${Math.round(project.media.bit_rate / 1000)} kbps` : "—"}</dd>
            </div>
            <div>
              <dt>大小</dt>
              <dd>{project.media?.size ? formatBytes(project.media.size) : "—"}</dd>
            </div>
            <div>
              <dt>视频</dt>
              <dd>
                {project.media?.has_video
                  ? `${project.media.video_width ?? "?"}×${project.media.video_height ?? "?"}`
                  : "无"}
              </dd>
            </div>
            <div>
              <dt>SHA256</dt>
              <dd title={project.media?.sha256}>{shortHash(project.media?.sha256 ?? "")}</dd>
            </div>
            <div>
              <dt>工作区</dt>
              <dd title={project.result_dir}>
                {settings?.workspace_dir || project.result_dir || "—"}
              </dd>
            </div>
            <div>
              <dt>创建时间</dt>
              <dd>{relativeTime(project.created_at)}</dd>
            </div>
          </dl>
        </div>

        <div className="card">
          <SectionTitle
            icon={<Sparkles size={15} />}
            title="最近任务"
            extra={
              <button type="button" className="link-btn" onClick={() => setSelectedTab("report")}>
                报告 <ArrowUpRight size={12} />
              </button>
            }
          />
          {projectJobs.length === 0 ? (
            <div className="muted">尚无任务记录。点击顶部「一键分析」开始。</div>
          ) : (
            <ul className="mini-job-list">
              {projectJobs.map((job: Job) => (
                <li key={job.id} className={`mini-job job-${job.status}`}>
                  <span className={`mini-job-dot status-${job.status}`} />
                  <span className="mini-job-kind">{JOB_KIND_TEXT[job.kind] ?? job.kind}</span>
                  <span className="mini-job-stage">{stageText(job.stage) || JOB_STATUS_TEXT[job.status]}</span>
                  <span className="mini-job-time">{relativeTime(job.created_at)}</span>
                </li>
              ))}
            </ul>
          )}

          {warnings.length > 0 ? (
            <>
              <SectionTitle icon={<AlertTriangle size={15} />} title="警告" />
              <ul className="warning-list">
                {warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </>
          ) : null}
        </div>
      </div>

      {loading ? (
        <div className="overview-loading" aria-hidden="true">
          <Loader2 size={13} className="spin" /> 正在同步分析结果…
        </div>
      ) : null}
    </div>
  );
}

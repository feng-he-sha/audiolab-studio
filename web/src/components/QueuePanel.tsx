/** Right sidebar: job queue + quick inspector for the selected project. */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  FileAudio,
  Gauge,
  ListTodo,
  Loader2,
  RefreshCw,
  RotateCcw,
  ScrollText,
  Sparkles,
  Square,
  Wand2,
  XCircle,
} from "lucide-react";
import type { Job, JobStatus } from "../api/types";
import { describeError } from "../api/client";
import { useStudio } from "../state/StudioContext";
import { useToast } from "../state/ui";
import {
  JOB_KIND_TEXT,
  JOB_STATUS_TEXT,
  LABEL_TEXT,
  STATUS_TEXT,
  elapsedTime,
  formatDuration,
  normalizeProgress,
  relativeTime,
  stageText,
} from "../utils/format";
import { useLocalStorage } from "../utils/hooks";
import { Chip, EmptyState, ProgressBar, StatusDot } from "./common/ui";

const STATUS_ICON: Record<JobStatus, ReactNode> = {
  queued: <Clock size={14} />,
  running: <Loader2 size={14} className="spin" />,
  done: <CheckCircle2 size={14} />,
  failed: <XCircle size={14} />,
  canceled: <Ban size={14} />,
  interrupted: <AlertTriangle size={14} />,
};

function JobCard({
  job,
  projectName,
  expanded,
  onToggle,
  onCancel,
  onRetry,
  busy,
  onSelectProject,
}: {
  job: Job;
  projectName: string;
  expanded: boolean;
  onToggle: () => void;
  onCancel: () => void;
  onRetry: () => void;
  busy: boolean;
  onSelectProject: () => void;
}): ReactNode {
  const active = job.status === "running" || job.status === "queued";
  const elapsed = elapsedTime(job.started_at || job.created_at, job.finished_at);
  const ratio = normalizeProgress(job.progress);
  return (
    <div className={`job-card job-${job.status}`}>
      <div
        className="job-head"
        role="button"
        tabIndex={0}
        onClick={onToggle}
        onKeyDown={(event) => {
          if (event.key === "Enter") onToggle();
        }}
      >
        <span className={`job-icon job-icon-${job.status}`}>{STATUS_ICON[job.status]}</span>
        <div className="job-title-wrap">
          <div className="job-title">
            <span className="job-kind">{JOB_KIND_TEXT[job.kind] ?? job.kind}</span>
            <span className="job-status">{JOB_STATUS_TEXT[job.status] ?? job.status}</span>
          </div>
          <div className="job-sub" title={projectName}>
            {projectName || (job.kind === "download" ? String(job.params?.model_id ?? "模型") : "系统任务")}
            <span className="job-elapsed">{elapsed}</span>
          </div>
        </div>
        <span className="job-chevron">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
      </div>

      {active ? (
        <div className="job-progress-row">
          <ProgressBar
            value={ratio}
            animated={job.status === "running"}
            tone={job.status === "queued" ? "var(--muted)" : undefined}
          />
          <span className="job-percent">{Math.round(ratio * 100)}%</span>
        </div>
      ) : null}

      {job.stage || job.message ? (
        <div className="job-stage">
          <span className="job-stage-name">{stageText(job.stage)}</span>
          {job.message ? <span className="job-message">{job.message}</span> : null}
        </div>
      ) : null}

      {job.error ? <div className="job-error">{job.error}</div> : null}

      <div className="job-actions">
        {job.project_id ? (
          <button type="button" className="link-btn" onClick={onSelectProject}>
            <FileAudio size={12} /> 打开项目
          </button>
        ) : (
          <span />
        )}
        <span className="job-time">{relativeTime(job.created_at)}</span>
        {active ? (
          <button type="button" className="btn btn-xs" onClick={onCancel} disabled={busy}>
            <Square size={11} /> 取消
          </button>
        ) : null}
        {(job.status === "failed" || job.status === "canceled" || job.status === "interrupted") ? (
          <button type="button" className="btn btn-xs" onClick={onRetry} disabled={busy}>
            <RotateCcw size={11} /> 重试
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function QueuePanel(): ReactNode {
  const {
    client,
    projects,
    jobs,
    jobsError,
    refreshJobs,
    selectedProject,
    selectProject,
    setSelectedTab,
    setView,
    toast,
    demo,
  } = useStudio();
  const [tab, setTab] = useLocalStorage<"queue" | "inspector">("audiolab.rightTab", "queue");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [logs, setLogs] = useState<Record<string, string[]>>({});
  const [busyJob, setBusyJob] = useState<string | null>(null);

  const projectNames = useMemo(() => {
    const map = new Map<string, string>();
    for (const project of projects) map.set(project.id, project.name);
    return map;
  }, [projects]);

  const activeJobs = useMemo(
    () => jobs.filter((job) => job.status === "running" || job.status === "queued"),
    [jobs],
  );
  const recentJobs = useMemo(
    () =>
      jobs
        .filter((job) => job.status !== "running" && job.status !== "queued")
        .slice(0, 25),
    [jobs],
  );

  useEffect(() => {
    if (!expanded) return undefined;
    let cancelled = false;
    const load = async () => {
      try {
        const response = await client.jobLog(expanded);
        if (!cancelled) {
          setLogs((prev) => ({ ...prev, [expanded]: response.lines.slice(-14) }));
        }
      } catch {
        if (!cancelled) {
          setLogs((prev) => ({ ...prev, [expanded]: ["[界面] 无法读取日志（后端可能未启动）。"] }));
        }
      }
    };
    void load();
    const timer = window.setInterval(load, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [client, expanded, jobs]);

  const onCancel = async (job: Job) => {
    setBusyJob(job.id);
    try {
      await client.cancelJob(job.id);
      toast.info("任务已取消");
      await refreshJobs();
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setBusyJob(null);
    }
  };

  const onRetry = async (job: Job) => {
    setBusyJob(job.id);
    try {
      await client.retryJob(job.id);
      toast.success("已重新提交任务");
      await refreshJobs();
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setBusyJob(null);
    }
  };

  const renderJob = (job: Job): ReactNode => (
    <div key={job.id}>
      <JobCard
        job={job}
        projectName={projectNames.get(job.project_id) ?? ""}
        expanded={expanded === job.id}
        onToggle={() => setExpanded(expanded === job.id ? null : job.id)}
        onCancel={() => void onCancel(job)}
        onRetry={() => void onRetry(job)}
        busy={busyJob === job.id}
        onSelectProject={() => job.project_id && selectProject(job.project_id)}
      />
      {expanded === job.id ? (
        <div className="job-log">
          <div className="job-log-head">
            <ScrollText size={12} /> 日志尾部
          </div>
          <pre>{(logs[job.id] ?? ["加载日志…"]).join("\n")}</pre>
        </div>
      ) : null}
    </div>
  );

  return (
    <aside className="right-panel">
      <div className="right-tabs">
        <button
          type="button"
          className={`right-tab${tab === "queue" ? " active" : ""}`}
          onClick={() => setTab("queue")}
        >
          <ListTodo size={14} /> 任务队列
          {activeJobs.length > 0 ? <span className="tab-badge">{activeJobs.length}</span> : null}
        </button>
        <button
          type="button"
          className={`right-tab${tab === "inspector" ? " active" : ""}`}
          onClick={() => setTab("inspector")}
        >
          <Gauge size={14} /> 检查器
        </button>
        <button type="button" className="icon-btn right-refresh" title="刷新任务" onClick={() => void refreshJobs()}>
          <RefreshCw size={13} />
        </button>
      </div>

      {tab === "queue" ? (
        <div className="queue-body">
          {jobsError ? (
            <EmptyState
              compact
              icon={<AlertTriangle size={18} />}
              title="任务队列不可用"
              description={jobsError}
              action={
                <button type="button" className="btn btn-xs" onClick={() => void refreshJobs()}>
                  <RefreshCw size={12} /> 重试
                </button>
              }
            />
          ) : null}
          <div className="queue-section">
            <div className="queue-section-title">
              进行中
              <span>{activeJobs.length}</span>
            </div>
            {activeJobs.length === 0 ? (
              <div className="queue-idle">
                <CheckCircle2 size={14} /> 当前没有运行中的任务
              </div>
            ) : (
              activeJobs.map(renderJob)
            )}
          </div>
          <div className="queue-section">
            <div className="queue-section-title">
              最近任务
              <span>{recentJobs.length}</span>
            </div>
            {recentJobs.length === 0 ? (
              <div className="queue-idle">
                <Sparkles size={14} /> 分析或处理后，任务会显示在这里
              </div>
            ) : (
              recentJobs.map(renderJob)
            )}
          </div>
        </div>
      ) : (
        <div className="inspector-body">
          {!selectedProject ? (
            <EmptyState
              compact
              icon={<FileAudio size={22} />}
              title="未选择项目"
              description="在左侧项目库选择一个项目查看详情。"
            />
          ) : (
            <>
              <div className="inspector-head">
                <StatusDot status={selectedProject.status} />
                <div>
                  <div className="inspector-name" title={selectedProject.source_path}>
                    {selectedProject.name}
                  </div>
                  <div className="inspector-status">
                    {STATUS_TEXT[selectedProject.status]} · 更新于 {relativeTime(selectedProject.updated_at)}
                  </div>
                </div>
              </div>

              <div className="inspector-grid">
                <div>
                  <span className="k">时长</span>
                  <span className="v">
                    {selectedProject.media ? formatDuration(selectedProject.media.duration) : "—"}
                  </span>
                </div>
                <div>
                  <span className="k">格式</span>
                  <span className="v">
                    {selectedProject.media
                      ? `${selectedProject.media.codec || "?"} · ${selectedProject.media.sample_rate / 1000} kHz`
                      : "—"}
                  </span>
                </div>
                <div>
                  <span className="k">声道</span>
                  <span className="v">{selectedProject.media?.channels ?? "—"}</span>
                </div>
                <div>
                  <span className="k">响度</span>
                  <span className="v">
                    {selectedProject.summary?.integrated_lufs !== undefined
                      ? `${selectedProject.summary.integrated_lufs} LUFS`
                      : "—"}
                  </span>
                </div>
              </div>

              <div className="inspector-section">
                <div className="inspector-section-title">标签时长占比</div>
                {(["vocals", "music", "vocals+music", "other"] as const).map((label) => {
                  const seconds = Number(selectedProject.summary?.[label] ?? 0);
                  const duration = selectedProject.media?.duration ?? 0;
                  const ratio = duration > 0 ? Math.min(1, seconds / duration) : 0;
                  return (
                    <div className="label-bar-row" key={label}>
                      <span className={`label-name label-${label}`}>{LABEL_TEXT[label]}</span>
                      <div className="label-bar">
                        <div className={`label-bar-fill label-${label}`} style={{ width: `${ratio * 100}%` }} />
                      </div>
                      <span className="label-seconds">{seconds.toFixed(1)}s</span>
                    </div>
                  );
                })}
              </div>

              {selectedProject.tags.length > 0 ? (
                <div className="inspector-section">
                  <div className="inspector-section-title">标签</div>
                  <div className="tag-cloud">
                    {selectedProject.tags.map((tag) => (
                      <Chip key={tag}>{tag}</Chip>
                    ))}
                  </div>
                </div>
              ) : null}

              {selectedProject.error ? (
                <div className="inspector-error">{selectedProject.error}</div>
              ) : null}

              <div className="inspector-actions">
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => {
                    setView("studio");
                    setSelectedTab("timeline");
                  }}
                >
                  <Wand2 size={13} /> 时间轴
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => {
                    setView("studio");
                    setSelectedTab("process");
                  }}
                >
                  <Sparkles size={13} /> 处理
                </button>
              </div>

              {demo ? (
                <div className="inspector-demo-note">
                  演示模式：数据为内置样例，音频文件不可播放。
                </div>
              ) : null}
            </>
          )}
        </div>
      )}
    </aside>
  );
}

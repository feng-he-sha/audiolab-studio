/** Center workspace: project header + six tabs. */
import { useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  FileAudio,
  FileText,
  Layers,
  Loader2,
  RefreshCw,
  Scan,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Waves,
  X,
} from "lucide-react";
import type { Quality } from "../api/types";
import { describeError } from "../api/client";
import { useStudio, type TabKey } from "../state/StudioContext";
import { useConfirm, useToast } from "../state/ui";
import { STATUS_TEXT, formatDuration, relativeTime, stageText } from "../utils/format";
import { StatusDot } from "./common/ui";
import { OverviewPanel } from "./OverviewPanel";
import { ReportPanel } from "./ReportPanel";
import { ProcessPanel } from "./ProcessPanel";
import { SeparationPanel } from "./SeparationPanel";
import { TimelinePanel } from "./TimelinePanel";
import { TimbrePanel } from "./TimbrePanel";

const TABS: { id: TabKey; label: string; icon: ReactNode }[] = [
  { id: "overview", label: "概览", icon: <Layers size={14} /> },
  { id: "timeline", label: "时间轴", icon: <Activity size={14} /> },
  { id: "separation", label: "分离", icon: <Waves size={14} /> },
  { id: "timbre", label: "音色", icon: <Scan size={14} /> },
  { id: "process", label: "处理", icon: <SlidersHorizontal size={14} /> },
  { id: "report", label: "报告", icon: <FileText size={14} /> },
];

export function ProjectView(): ReactNode {
  const {
    client,
    selectedProject,
    selectedTab,
    setSelectedTab,
    analyzeProject,
    jobs,
    setView,
    toast,
    refreshProjects,
  } = useStudio();
  const confirm = useConfirm();
  const [quality, setQuality] = useState<Quality>("balanced");
  const [analyzing, setAnalyzing] = useState(false);

  const activeJob = useMemo(
    () =>
      jobs.find(
        (job) =>
          job.project_id === selectedProject?.id &&
          (job.status === "running" || job.status === "queued"),
      ) ?? null,
    [jobs, selectedProject],
  );

  if (!selectedProject) return null;

  const runAnalyze = async () => {
    setAnalyzing(true);
    try {
      await analyzeProject(selectedProject.id, { quality });
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setAnalyzing(false);
    }
  };

  const removeProject = async () => {
    const ok = await confirm({
      title: `删除项目「${selectedProject.name}」？`,
      message: "将删除工作区中的分析结果与输出文件，此操作不可撤销。",
      confirmText: "删除项目",
      danger: true,
    });
    if (!ok) return;
    try {
      await client.deleteProject(selectedProject.id, true);
      await refreshProjects(true);
      setView("studio");
      toast.success("项目已删除");
    } catch (err) {
      toast.error(describeError(err));
    }
  };

  return (
    <div className="project-view">
      <div className="project-head">
        <div className="project-head-main">
          <div className="project-title-row">
            <StatusDot status={selectedProject.status} />
            <h1>{selectedProject.name}</h1>
            <span className="project-status">{STATUS_TEXT[selectedProject.status]}</span>
            {activeJob ? (
              <span className="project-active-job">
                <Loader2 size={12} className="spin" /> {stageText(activeJob.stage)}
              </span>
            ) : null}
          </div>
          <div className="project-meta">
            <span>
              <FileAudio size={12} /> {selectedProject.media?.filename ?? "未知媒体"}
            </span>
            <span>{selectedProject.media ? formatDuration(selectedProject.media.duration) : "—"}</span>
            <span>更新于 {relativeTime(selectedProject.updated_at)}</span>
            {selectedProject.media?.has_video ? (
              <span>
                {selectedProject.media.video_width}×{selectedProject.media.video_height}
              </span>
            ) : null}
          </div>
        </div>
        <div className="project-head-actions">
          <select
            className="quality-select"
            value={quality}
            onChange={(event) => setQuality(event.target.value as Quality)}
            title="分析质量"
            aria-label="分析质量"
          >
            <option value="fast">快速</option>
            <option value="balanced">均衡</option>
            <option value="hq">高质量</option>
          </select>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => void runAnalyze()}
            disabled={analyzing || Boolean(activeJob)}
          >
            {analyzing || activeJob ? <Loader2 size={14} className="spin" /> : <Sparkles size={14} />}
            {selectedProject.status === "imported" ? "一键分析" : "重新分析"}
          </button>
          <button type="button" className="icon-btn" title="刷新项目" onClick={() => void refreshProjects(true)}>
            <RefreshCw size={14} />
          </button>
          <button type="button" className="icon-btn danger" title="删除项目" onClick={() => void removeProject()}>
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {selectedProject.error ? (
        <div className="banner banner-danger">
          <AlertTriangle size={15} /> {selectedProject.error}
          <button type="button" className="link-btn" onClick={() => void runAnalyze()}>
            重新分析
          </button>
        </div>
      ) : null}

      <div className="project-tabs" role="tablist">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={selectedTab === tab.id}
            className={`project-tab${selectedTab === tab.id ? " active" : ""}`}
            onClick={() => setSelectedTab(tab.id)}
          >
            {tab.icon} {tab.label}
          </button>
        ))}
        <span className="project-tabs-spacer" />
      </div>

      <div className="project-tab-body" role="tabpanel">
        {selectedTab === "overview" ? <OverviewPanel /> : null}
        {selectedTab === "timeline" ? <TimelinePanel /> : null}
        {selectedTab === "separation" ? <SeparationPanel /> : null}
        {selectedTab === "timbre" ? <TimbrePanel /> : null}
        {selectedTab === "process" ? <ProcessPanel /> : null}
        {selectedTab === "report" ? <ReportPanel /> : null}
      </div>
    </div>
  );
}

export function CloseIcon(): ReactNode {
  return <X size={14} />;
}

/** Empty-state workspace shown before a project is selected. */
import { type ReactNode } from "react";
import {
  ArrowRight,
  Cpu,
  FileAudio,
  FolderOpen,
  Scissors,
  Sparkles,
  Upload,
  Waves,
} from "lucide-react";
import { useStudio } from "../state/StudioContext";
import { STATUS_TEXT, formatDuration, relativeTime } from "../utils/format";
import { EmptyState, StatusDot } from "./common/ui";

const STEPS = [
  {
    icon: <Upload size={18} />,
    title: "1. 导入媒体",
    desc: "拖拽文件到窗口，或使用导入按钮 / 原生文件对话框。",
  },
  {
    icon: <Waves size={18} />,
    title: "2. 一键分析",
    desc: "VAD 分段、AST 标签、融合、音色聚类与人声分离一次完成。",
  },
  {
    icon: <Scissors size={18} />,
    title: "3. 处理与导出",
    desc: "选择抖音/播客等预设，渲染后 A/B 对比并导出成片。",
  },
];

export function Welcome(): ReactNode {
  const { projects, selectProject, projectsLoading } = useStudio();
  const recent = projects.slice(0, 6);

  const triggerImport = () => {
    window.dispatchEvent(new CustomEvent("audiolab:import"));
  };

  return (
    <div className="welcome">
      <div className="welcome-hero">
        <div className="welcome-logo">
          <Waves size={30} />
        </div>
        <h1>AudioLab Studio</h1>
        <p className="welcome-sub">
          本地音频人声工作台：语义分段、音色聚类、人声分离与抖音响度处理，全流程离线运行。
        </p>
        <div className="welcome-chips">
          <span className="welcome-chip"><Cpu size={12} /> 自动选择 CUDA / CPU</span>
          <span className="welcome-chip"><Sparkles size={12} /> Silero VAD + AST</span>
          <span className="welcome-chip"><FileAudio size={12} /> BS-Roformer 分离</span>
          <span className="welcome-chip"><FolderOpen size={12} /> 全本地工作区</span>
        </div>
        <div className="welcome-actions">
          <button type="button" className="btn btn-primary" onClick={triggerImport}>
            <Upload size={16} /> 导入音频 / 视频
          </button>
          {recent.length > 0 ? (
            <button
              type="button"
              className="btn"
              onClick={() => selectProject(recent[0].id)}
            >
              打开最近项目 <ArrowRight size={15} />
            </button>
          ) : null}
        </div>
      </div>

      <div className="welcome-steps">
        {STEPS.map((step) => (
          <div className="welcome-step" key={step.title}>
            <span className="welcome-step-icon">{step.icon}</span>
            <div>
              <div className="welcome-step-title">{step.title}</div>
              <div className="welcome-step-desc">{step.desc}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="welcome-recent">
        <div className="welcome-recent-head">
          <h2>最近项目</h2>
          <span className="muted">{projects.length} 个项目</span>
        </div>
        {projectsLoading && projects.length === 0 ? (
          <div className="muted">加载项目库…</div>
        ) : recent.length === 0 ? (
          <EmptyState
            compact
            icon={<FileAudio size={22} />}
            title="项目库还是空的"
            description="导入第一个音频或视频文件开始分析。"
            action={
              <button type="button" className="btn btn-primary btn-sm" onClick={triggerImport}>
                <Upload size={14} /> 导入媒体
              </button>
            }
          />
        ) : (
          <div className="welcome-recent-grid">
            {recent.map((project) => (
              <button
                type="button"
                key={project.id}
                className="welcome-project"
                onClick={() => selectProject(project.id)}
              >
                <div className="welcome-project-head">
                  <StatusDot status={project.status} />
                  <span className="welcome-project-name">{project.name}</span>
                </div>
                <div className="welcome-project-meta">
                  <span>{project.media ? formatDuration(project.media.duration) : "—"}</span>
                  <span>{STATUS_TEXT[project.status]}</span>
                  <span>{relativeTime(project.updated_at)}</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

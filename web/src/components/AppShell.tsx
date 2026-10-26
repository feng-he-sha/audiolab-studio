/** Application shell: topbar, library, workspace, queue, status bar, log drawer. */
import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Cpu,
  FolderKanban,
  Loader2,
  Package,
  Settings,
  Sparkles,
  Stethoscope,
  Upload,
  Waves,
  Wand2,
} from "lucide-react";
import { describeError } from "../api/client";
import { useStudio } from "../state/StudioContext";
import { Library } from "./Library";
import { LogDrawer } from "./LogDrawer";
import { ModelsPanel } from "./ModelsPanel";
import { ProjectView } from "./ProjectView";
import { QueuePanel } from "./QueuePanel";
import { SettingsPanel } from "./SettingsPanel";
import { DoctorPanel } from "./DoctorPanel";
import { StatusBar } from "./StatusBar";
import { Welcome } from "./Welcome";
import { ErrorBoundary } from "./common/ErrorBoundary";

export function AppShell(): ReactNode {
  const {
    view,
    setView,
    selectedProject,
    analyzeProject,
    uploadFiles,
    health,
    demo,
    toast,
    selectedTab,
  } = useStudio();
  const [analyzing, setAnalyzing] = useState(false);
  const [dragging, setDragging] = useState(false);
  const dragDepth = useRef(0);

  useEffect(() => {
    const hasFiles = (event: DragEvent): boolean =>
      Array.from(event.dataTransfer?.types ?? []).includes("Files");

    const onDragEnter = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      dragDepth.current += 1;
      setDragging(true);
    };
    const onDragOver = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      event.dataTransfer!.dropEffect = "copy";
    };
    const onDragLeave = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      dragDepth.current = Math.max(0, dragDepth.current - 1);
      if (dragDepth.current === 0) setDragging(false);
    };
    const onDrop = async (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      dragDepth.current = 0;
      setDragging(false);
      const files = Array.from(event.dataTransfer?.files ?? []);
      if (files.length === 0) return;
      try {
        const result = await uploadFiles(files);
        if (result.errors.length > 0) toast.warn(`部分文件未导入：${result.errors[0]}`);
        if (result.projects.length > 0) toast.success(`已导入 ${result.projects.length} 个项目`);
      } catch (err) {
        toast.error(describeError(err));
      }
    };

    window.addEventListener("dragenter", onDragEnter);
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("dragleave", onDragLeave);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragenter", onDragEnter);
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("dragleave", onDragLeave);
      window.removeEventListener("drop", onDrop);
    };
  }, [toast, uploadFiles]);

  const analyzeCurrent = async () => {
    if (!selectedProject) {
      toast.warn("请先在项目库选择一个项目。");
      return;
    }
    setAnalyzing(true);
    try {
      await analyzeProject(selectedProject.id, { quality: "balanced" });
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setAnalyzing(false);
    }
  };

  const dispatchImport = () => window.dispatchEvent(new CustomEvent("audiolab:import"));
  const dispatchBatch = () => window.dispatchEvent(new CustomEvent("audiolab:batch"));

  return (
    <div className="app-shell">
      <header className="topbar">
        <button type="button" className="brand" onClick={() => setView("studio")} title="返回工作台">
          <span className="brand-logo">
            <Waves size={19} />
          </span>
          <span className="brand-text">
            <span className="brand-name">AudioLab Studio</span>
            <span className="brand-sub">音频人声工作台</span>
          </span>
        </button>

        <div className="topbar-divider" />

        <div className="topbar-actions">
          <button type="button" className="btn btn-primary btn-sm" onClick={dispatchImport}>
            <Upload size={14} /> 导入
          </button>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => void analyzeCurrent()}
            disabled={!selectedProject || analyzing}
            title={selectedProject ? `分析「${selectedProject.name}」` : "请先选择项目"}
          >
            {analyzing ? <Loader2 size={14} className="spin" /> : <Wand2 size={14} />} 一键分析
          </button>
          <button type="button" className="btn btn-sm" onClick={dispatchBatch}>
            <Sparkles size={14} /> 批量处理
          </button>
        </div>

        <span className="topbar-spacer" />

        <div className="topbar-status">
          {health ? (
            <>
              <span className="top-chip" title={health.cuda ? "CUDA 可用" : "CUDA 不可用，使用 CPU"}>
                <Cpu size={13} /> {(health.device || "cpu").toUpperCase()}
              </span>
              <span className={`top-chip ${health.ffmpeg ? "ok" : "bad"}`} title="ffmpeg 状态">
                ffmpeg
              </span>
            </>
          ) : (
            <span className="top-chip bad">后端未连接</span>
          )}
        </div>

        <nav className="topbar-nav" aria-label="主导航">
          <button
            type="button"
            className={`icon-btn nav-btn${view === "studio" ? " active" : ""}`}
            title="工作台"
            onClick={() => setView("studio")}
          >
            <FolderKanban size={17} />
          </button>
          <button
            type="button"
            className={`icon-btn nav-btn${view === "models" ? " active" : ""}`}
            title="模型与引擎"
            onClick={() => setView("models")}
          >
            <Package size={17} />
          </button>
          <button
            type="button"
            className={`icon-btn nav-btn${view === "doctor" ? " active" : ""}`}
            title="诊断"
            onClick={() => setView("doctor")}
          >
            <Stethoscope size={17} />
          </button>
          <button
            type="button"
            className={`icon-btn nav-btn${view === "settings" ? " active" : ""}`}
            title="设置"
            onClick={() => setView("settings")}
          >
            <Settings size={17} />
          </button>
        </nav>
      </header>

      <div className="app-body">
        <Library />
        <main className="workspace">
          <ErrorBoundary key={`${view}:${selectedProject?.id ?? "none"}:${selectedTab}`}>
            {view === "studio" ? (
              selectedProject ? (
                <ProjectView />
              ) : (
                <Welcome />
              )
            ) : view === "models" ? (
              <ModelsPanel />
            ) : view === "settings" ? (
              <SettingsPanel />
            ) : (
              <DoctorPanel />
            )}
          </ErrorBoundary>
        </main>
        <QueuePanel />
      </div>

      <LogDrawer />
      <StatusBar />

      {dragging ? (
        <div className="drop-overlay">
          <div className="drop-card">
            <Upload size={30} />
            <div className="drop-title">松开以导入媒体</div>
            <div className="muted">支持 mp3 / wav / flac / m4a / mp4 / mov / mkv 等格式</div>
          </div>
        </div>
      ) : null}

      {demo ? <div className="demo-ribbon">演示模式 · 内置数据</div> : null}
    </div>
  );
}

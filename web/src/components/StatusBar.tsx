/** Bottom status bar: backend state, selected project, log drawer toggle. */
import type { ReactNode } from "react";
import {
  AlertTriangle,
  ChevronUp,
  Circle,
  FileAudio,
  ScrollText,
  Server,
  Sparkles,
} from "lucide-react";
import { useStudio } from "../state/StudioContext";
import { STATUS_TEXT, formatDuration } from "../utils/format";

export function StatusBar(): ReactNode {
  const { health, healthError, wsConnected, selectedProject, logOpen, setLogOpen, demo } = useStudio();

  const online = Boolean(health?.ok) && !healthError;
  return (
    <footer className="statusbar">
      <div className="statusbar-left">
        <span className={`status-connection ${online ? "online" : "offline"}`} title={healthError || "后端连接正常"}>
          <span className="status-connection-dot" />
          <Server size={12} />
          {online ? `后端 v${health?.version ?? "?"}` : "后端未连接"}
        </span>
        <span className={`status-ws ${wsConnected ? "live" : ""}`} title={wsConnected ? "WebSocket 实时事件已连接" : "WebSocket 未连接，使用轮询"}>
          <Circle size={7} /> {wsConnected ? "实时" : "轮询"}
        </span>
        {health ? (
          <span className="status-device">
            {health.device?.toUpperCase()}
            {health.cuda ? " · CUDA" : ""}
          </span>
        ) : null}
        {health ? <span className={`status-chip ${health.ffmpeg ? "ok" : "bad"}`}>ffmpeg {health.ffmpeg ? "可用" : "缺失"}</span> : null}
        {demo ? <span className="status-chip demo"><Sparkles size={11} /> 演示模式</span> : null}
      </div>

      <div className="statusbar-center">
        {selectedProject ? (
          <>
            <FileAudio size={12} />
            <span className="status-project-name" title={selectedProject.source_path}>
              {selectedProject.name}
            </span>
            <span className="muted">{STATUS_TEXT[selectedProject.status]}</span>
            <span className="muted">
              {selectedProject.media ? formatDuration(selectedProject.media.duration) : "—"}
            </span>
          </>
        ) : (
          <span className="muted">未选择项目</span>
        )}
        {healthError ? (
          <span className="status-error" title={healthError}>
            <AlertTriangle size={11} /> {healthError.slice(0, 64)}
          </span>
        ) : null}
      </div>

      <div className="statusbar-right">
        <button
          type="button"
          className={`statusbar-log-btn${logOpen ? " active" : ""}`}
          onClick={() => setLogOpen(!logOpen)}
          title="展开/收起日志抽屉"
        >
          <ScrollText size={13} /> 日志 <ChevronUp size={12} className={logOpen ? "flip" : ""} />
        </button>
        <span className="statusbar-hint">空格播放 · ←/→ 快移 · 1-4 过滤 · F 适配</span>
      </div>
    </footer>
  );
}

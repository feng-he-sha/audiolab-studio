/** 分离 tab: original / vocals / instrumental stems with synced playback. */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Download,
  FileAudio,
  Headphones,
  Music,
  RefreshCw,
  Sparkles,
  Upload,
  Waves,
} from "lucide-react";
import { describeError } from "../api/client";
import type { Artifact } from "../api/types";
import type { TransportTrack } from "../audio/Transport";
import { useTransport } from "../audio/useTransport";
import { useStudio } from "../state/StudioContext";
import { useToast } from "../state/ui";
import { formatBytes, formatDuration } from "../utils/format";
import { useKeyboard } from "../utils/hooks";
import { EmptyState, LoadingBlock } from "./common/ui";
import { TransportBar } from "./TransportBar";

const TRACK_META: Record<string, { label: string; icon: ReactNode; color: string }> = {
  original: { label: "原声", icon: <FileAudio size={17} />, color: "var(--muted)" },
  vocals: { label: "人声", icon: <Headphones size={17} />, color: "var(--vocals)" },
  instrumental: { label: "伴奏", icon: <Music size={17} />, color: "var(--music)" },
};

export function SeparationPanel(): ReactNode {
  const { client, demo, selectedProject, dataVersion, analyzeProject, toast } = useStudio();
  const projectId = selectedProject?.id ?? "";
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [analysisBusy, setAnalysisBusy] = useState(false);

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const response = await client.artifacts(projectId);
      setArtifacts(response.artifacts);
      setError("");
    } catch (err) {
      setError(describeError(err));
    } finally {
      setLoading(false);
    }
  }, [client, projectId]);

  useEffect(() => {
    void load();
  }, [load, dataVersion]);

  const byKind = useMemo(() => {
    const map: Partial<Record<"original" | "vocals" | "instrumental", Artifact>> = {};
    for (const artifact of artifacts) {
      if (artifact.kind === "original" || artifact.kind === "vocals" || artifact.kind === "instrumental") {
        if (!map[artifact.kind]) map[artifact.kind] = artifact;
      }
    }
    return map;
  }, [artifacts]);

  const stems = (["original", "vocals", "instrumental"] as const)
    .map((kind) => byKind[kind])
    .filter((item): item is Artifact => Boolean(item));

  const tracks: TransportTrack[] = useMemo(
    () =>
      stems.map((artifact) => ({
        id: artifact.kind,
        label: TRACK_META[artifact.kind]?.label ?? artifact.label,
        url: demo ? "" : artifact.url,
        color: TRACK_META[artifact.kind]?.color,
        kind: artifact.kind,
      })),
    [stems, demo],
  );

  const duration = selectedProject?.media?.duration ?? stems[0]?.duration ?? 0;
  const transportKey = `${projectId}:separation:${stems.map((s) => s.id).join(",")}:${duration.toFixed(2)}`;
  const { transport, snapshot, time } = useTransport(transportKey, tracks, {
    duration,
    simulated: demo,
    loop: false,
  });

  const analyze = async () => {
    setAnalysisBusy(true);
    try {
      await analyzeProject(projectId);
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setAnalysisBusy(false);
    }
  };

  useKeyboard((event) => {
    if (!transport) return;
    if (event.code === "Space") {
      event.preventDefault();
      transport.toggle();
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      transport.seek(transport.currentTime() - 2);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      transport.seek(transport.currentTime() + 2);
    }
  });

  const exportStem = (artifact: Artifact) => {
    if (demo) {
      toast.warn("演示模式没有真实 stem 文件，无法导出。");
      return;
    }
    const anchor = document.createElement("a");
    anchor.href = artifact.url;
    anchor.download = `${selectedProject?.name ?? "stem"}_${artifact.kind}.wav`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    toast.info(`已开始导出「${artifact.label}」`);
  };

  const soloAndPlay = (artifact: Artifact) => {
    transport?.setMix(artifact.kind, { solo: true, mute: false });
    void transport?.play();
  };

  if (!projectId) return <EmptyState title="未选择项目" />;

  if (loading && artifacts.length === 0) return <LoadingBlock label="正在读取分离结果…" rows={3} />;

  if (error && artifacts.length === 0) {
    return (
      <EmptyState
        icon={<AlertTriangle size={24} />}
        title="无法读取分离结果"
        description={error}
        action={
          <button type="button" className="btn btn-sm" onClick={() => void load()}>
            <RefreshCw size={13} /> 重试
          </button>
        }
      />
    );
  }

  if (stems.length === 0) {
    return (
      <EmptyState
        icon={<Waves size={26} />}
        title="尚未生成音轨分离"
        description="分析任务会使用 BS-Roformer（失败时回退 MDX-NET）分离人声与伴奏。"
        action={
          <button type="button" className="btn btn-primary btn-sm" onClick={() => void analyze()} disabled={analysisBusy}>
            {analysisBusy ? <Sparkles size={14} className="spin" /> : <Upload size={14} />} 开始分析
          </button>
        }
      />
    );
  }

  return (
    <div className="separation-panel">
      <div className="stem-cards">
        {stems.map((artifact) => {
          const meta = TRACK_META[artifact.kind];
          const mix = transport?.getMix(artifact.kind);
          return (
            <div className={`stem-card${mix?.solo ? " soloed" : ""}`} key={artifact.id}>
              <div className="stem-card-head">
                <span className="stem-icon" style={{ color: meta?.color }}>
                  {meta?.icon ?? <FileAudio size={17} />}
                </span>
                <div className="stem-title">
                  <span>{meta?.label ?? artifact.label}</span>
                  <span className="muted">{artifact.mime || ".wav"}</span>
                </div>
                <span className="stem-ready">已就绪</span>
              </div>
              <div className="stem-meta">
                <span>{formatDuration(artifact.duration || duration)}</span>
                <span>{formatBytes(artifact.size)}</span>
              </div>
              <div className="stem-actions">
                <button type="button" className="btn btn-xs" onClick={() => soloAndPlay(artifact)} disabled={!transport}>
                  <Headphones size={12} /> 独奏播放
                </button>
                <button type="button" className="btn btn-xs" onClick={() => exportStem(artifact)}>
                  <Download size={12} /> 导出
                </button>
              </div>
            </div>
          );
        })}
      </div>

      <TransportBar
        transport={transport}
        snapshot={snapshot}
        time={time}
        tracks={tracks}
        showTracks
        onError={(message) => toast.warn(message)}
      />

      <div className="hint-row">
        <span>
          播放使用 Web Audio 同步多轨：同一 AudioContext 时间启动，各 stem 独立 GainNode，可实时 solo / mute / 调音量。
        </span>
        {snapshot.mode === "element" ? <span className="muted">已回退为单轨 HTML5 播放。</span> : null}
        {demo ? <span className="muted">演示模式下为模拟时钟播放。</span> : null}
      </div>
    </div>
  );
}

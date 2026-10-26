/** 处理 tab: presets, parameter form, render, preview + A/B comparison. */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  Check,
  Download,
  ExternalLink,
  Loader2,
  Music4,
  Play,
  RefreshCw,
  SlidersHorizontal,
  Sparkles,
  Volume2,
} from "lucide-react";
import { describeError } from "../api/client";
import type { Artifact, Preset } from "../api/types";
import type { TransportTrack } from "../audio/Transport";
import { useTransport } from "../audio/useTransport";
import { useStudio } from "../state/StudioContext";
import { useToast } from "../state/ui";
import { JOB_STATUS_TEXT, formatBytes, formatDuration, formatNumber, relativeTime, stageText } from "../utils/format";
import { useKeyboard } from "../utils/hooks";
import { Chip, EmptyState, LoadingBlock, SectionTitle } from "./common/ui";
import { TransportBar } from "./TransportBar";

interface PresetSpec {
  id: Preset;
  label: string;
  desc: string;
  targetLufs: number;
  denoise: number;
  duckDb: number;
  format: string;
  accent: string;
}

const PRESETS: PresetSpec[] = [
  {
    id: "douyin",
    label: "抖音",
    desc: "短视频口播，响度最大化，轻降噪 + 人声触发闪避",
    targetLufs: -14,
    denoise: 0.35,
    duckDb: 3,
    format: "m4a",
    accent: "var(--accent)",
  },
  {
    id: "podcast",
    label: "播客",
    desc: "长对话，强降噪 + 温和压缩，保持人声自然",
    targetLufs: -16,
    denoise: 0.55,
    duckDb: 2,
    format: "m4a",
    accent: "var(--vocals)",
  },
  {
    id: "movie",
    label: "影视",
    desc: "保留动态范围，对白优先，较大闪避量",
    targetLufs: -18,
    denoise: 0.3,
    duckDb: 6,
    format: "m4a",
    accent: "var(--mixed)",
  },
  {
    id: "music",
    label: "音乐",
    desc: "音乐为主，几乎不降噪，高保真输出",
    targetLufs: -12,
    denoise: 0.1,
    duckDb: 1.5,
    format: "wav",
    accent: "var(--music)",
  },
  {
    id: "clean",
    label: "纯净",
    desc: "仅降噪与响度归一，不做闪避",
    targetLufs: -16,
    denoise: 0.7,
    duckDb: 0,
    format: "wav",
    accent: "var(--warn)",
  },
];

const FORMATS = [
  { value: "m4a", label: "m4a（AAC）" },
  { value: "mp3", label: "mp3" },
  { value: "wav", label: "wav（无损）" },
];

export function ProcessPanel(): ReactNode {
  const { client, demo, selectedProject, dataVersion, jobs, processProject, toast } = useStudio();
  const projectId = selectedProject?.id ?? "";
  const [preset, setPreset] = useState<PresetSpec>(PRESETS[0]);
  const [targetLufs, setTargetLufs] = useState(PRESETS[0].targetLufs);
  const [denoise, setDenoise] = useState(PRESETS[0].denoise);
  const [duckDb, setDuckDb] = useState(PRESETS[0].duckDb);
  const [outputFormat, setOutputFormat] = useState(PRESETS[0].format);
  const [muxVideo, setMuxVideo] = useState(true);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [ab, setAb] = useState<"A" | "B">("A");

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const response = await client.artifacts(projectId);
      setArtifacts(response.artifacts);
    } catch {
      setArtifacts([]);
    } finally {
      setLoading(false);
    }
  }, [client, projectId]);

  useEffect(() => {
    void load();
  }, [load, dataVersion]);

  const original = useMemo(() => artifacts.find((item) => item.kind === "original") ?? null, [artifacts]);
  const processed = useMemo(() => artifacts.find((item) => item.kind === "processed") ?? null, [artifacts]);

  const duration = selectedProject?.media?.duration ?? processed?.duration ?? original?.duration ?? 0;

  const tracks: TransportTrack[] = useMemo(() => {
    const list: TransportTrack[] = [];
    if (original) {
      list.push({ id: "original", label: "A · 原声", url: demo ? "" : original.url, color: "var(--muted)", kind: "original" });
    }
    if (processed) {
      list.push({ id: "processed", label: "B · 处理后", url: demo ? "" : processed.url, color: "var(--accent)", kind: "processed" });
    }
    return list;
  }, [original, processed, demo]);

  const transportKey = `${projectId}:process:${original?.id ?? "none"}:${processed?.id ?? "none"}:${duration.toFixed(2)}`;
  const { transport, snapshot, time } = useTransport(transportKey, tracks, {
    duration,
    simulated: demo,
    loop: false,
  });

  useEffect(() => {
    if (!transport) return;
    transport.setMix("original", { gain: ab === "A" ? 1 : 0, mute: false, solo: false });
    transport.setMix("processed", { gain: ab === "B" ? 1 : 0, mute: false, solo: false });
  }, [transport, ab]);

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
    } else if (event.key === "a" || event.key === "A") {
      setAb("A");
    } else if ((event.key === "b" || event.key === "B") && processed) {
      setAb("B");
    }
  });

  const selectPreset = (spec: PresetSpec) => {
    setPreset(spec);
    setTargetLufs(spec.targetLufs);
    setDenoise(spec.denoise);
    setDuckDb(spec.duckDb);
    setOutputFormat(spec.format);
  };

  const render = async () => {
    setBusy(true);
    try {
      await processProject(projectId, {
        preset: preset.id,
        params: {
          target_lufs: targetLufs,
          denoise,
          duck_db: duckDb,
        },
        mux_video: muxVideo,
        output_format: outputFormat,
      });
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  const openOutput = () => {
    if (demo) {
      toast.warn("演示模式没有真实输出文件。");
      return;
    }
    const target = processed ?? (artifacts.find((item) => item.kind === "preview") ?? null);
    if (!target) {
      toast.warn("还没有输出文件，请先渲染。");
      return;
    }
    window.open(target.url, "_blank", "noopener,noreferrer");
  };

  const exportOutput = () => {
    if (demo || !processed) {
      toast.warn(demo ? "演示模式没有真实输出文件。" : "还没有输出文件，请先渲染。");
      return;
    }
    const anchor = document.createElement("a");
    anchor.href = processed.url;
    anchor.download = `${selectedProject?.name ?? "output"}_${preset.id}.${outputFormat}`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  };

  const lastProcessJob = useMemo(
    () =>
      jobs
        .filter((job) => job.project_id === projectId && job.kind === "process")
        .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0] ?? null,
    [jobs, projectId],
  );

  if (!projectId) return <EmptyState title="未选择项目" />;

  return (
    <div className="process-panel">
      <div className="preset-grid">
        {PRESETS.map((spec) => (
          <button
            key={spec.id}
            type="button"
            className={`preset-card${preset.id === spec.id ? " active" : ""}`}
            onClick={() => selectPreset(spec)}
            style={{ ["--preset-accent" as string]: spec.accent }}
          >
            <span className="preset-card-head">
              <span className="preset-name">{spec.label}</span>
              {preset.id === spec.id ? <Check size={15} className="preset-check" /> : null}
            </span>
            <span className="preset-desc">{spec.desc}</span>
            <span className="preset-meta">
              {spec.targetLufs} LUFS · 降噪 {Math.round(spec.denoise * 100)}% · 闪避 {spec.duckDb} dB
            </span>
          </button>
        ))}
      </div>

      <div className="process-layout">
        <div className="card process-form">
          <SectionTitle icon={<SlidersHorizontal size={15} />} title="处理参数" extra={<Chip tone={preset.accent}>{preset.label}预设</Chip>} />
          <div className="param-grid">
            <label className="field">
              <span className="field-label">目标响度（LUFS）</span>
              <input
                type="number"
                min={-30}
                max={-5}
                step={0.5}
                value={targetLufs}
                onChange={(event) => setTargetLufs(Number(event.target.value))}
              />
              <span className="field-hint">两遍 loudnorm，抖音常用 -14 LUFS</span>
            </label>
            <label className="field">
              <span className="field-label">降噪强度</span>
              <div className="range-field">
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={Math.round(denoise * 100)}
                  onChange={(event) => setDenoise(Number(event.target.value) / 100)}
                />
                <span>{Math.round(denoise * 100)}%</span>
              </div>
              <span className="field-hint">频谱降噪混合比例</span>
            </label>
            <label className="field">
              <span className="field-label">闪避量（dB）</span>
              <div className="range-field">
                <input
                  type="range"
                  min={0}
                  max={12}
                  step={0.5}
                  value={duckDb}
                  onChange={(event) => setDuckDb(Number(event.target.value))}
                />
                <span>{duckDb} dB</span>
              </div>
              <span className="field-hint">人声出现时压低音乐</span>
            </label>
            <label className="field">
              <span className="field-label">输出格式</span>
              <select value={outputFormat} onChange={(event) => setOutputFormat(event.target.value)}>
                {FORMATS.map((format) => (
                  <option key={format.value} value={format.value}>
                    {format.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="checkbox process-mux">
            <input type="checkbox" checked={muxVideo} onChange={(event) => setMuxVideo(event.target.checked)} />
            <span>回贴视频轨道（mux video）</span>
          </label>

          <div className="process-submit">
            <button type="button" className="btn btn-primary" onClick={() => void render()} disabled={busy}>
              {busy ? <Loader2 size={15} className="spin" /> : <Sparkles size={15} />} 开始渲染
            </button>
            <button type="button" className="btn" onClick={openOutput} disabled={!processed && !demo}>
              <ExternalLink size={14} /> 打开输出
            </button>
            <button type="button" className="btn" onClick={exportOutput} disabled={!processed}>
              <Download size={14} /> 导出文件
            </button>
          </div>

          {lastProcessJob ? (
            <div className={`process-job-note job-${lastProcessJob.status}`}>
              <span className="mini-job-dot" />
              最近一次处理：{JOB_STATUS_TEXT[lastProcessJob.status]} ·{" "}
              {lastProcessJob.message || stageText(lastProcessJob.stage)} ·{" "}
              {relativeTime(lastProcessJob.created_at)}
            </div>
          ) : null}
        </div>

        <div className="card process-preview">
          <SectionTitle icon={<Volume2 size={15} />} title="预览与 A / B 对比" />
          {loading && !processed ? (
            <LoadingBlock label="正在加载预览…" rows={2} />
          ) : !original && !processed ? (
            <EmptyState
              compact
              icon={<Music4 size={20} />}
              title="还没有可试听的音频"
              description="先完成分析生成原声/预览，再渲染处理结果。"
            />
          ) : (
            <>
              <div className="ab-switch">
                <button
                  type="button"
                  className={`ab-btn${ab === "A" ? " active" : ""}`}
                  onClick={() => setAb("A")}
                  title="原声"
                >
                  A · 原声
                </button>
                <button
                  type="button"
                  className={`ab-btn${ab === "B" ? " active" : ""}`}
                  onClick={() => setAb("B")}
                  disabled={!processed}
                  title="处理结果"
                >
                  B · 处理后
                </button>
                {!processed ? <span className="muted ab-hint">渲染完成后可切换 B</span> : null}
              </div>
              <TransportBar transport={transport} snapshot={snapshot} time={time} tracks={tracks} />
              <div className="preview-notes">
                <span>A/B 切换通过交叉调整两条轨道的 GainNode 实现，播放位置保持同步。</span>
              </div>
            </>
          )}

          {processed ? (
            <div className="output-meta">
              <div>
                <span className="k">输出</span>
                <span className="v" title={processed.path}>{processed.label}</span>
              </div>
              <div>
                <span className="k">时长</span>
                <span className="v">{formatDuration(processed.duration || duration)}</span>
              </div>
              <div>
                <span className="k">大小</span>
                <span className="v">{formatBytes(processed.size)}</span>
              </div>
              <div>
                <span className="k">响度</span>
                <span className="v">
                  {selectedProject?.summary?.integrated_lufs !== undefined
                    ? `${formatNumber(Number(selectedProject.summary.integrated_lufs))} LUFS`
                    : "—"}
                </span>
              </div>
            </div>
          ) : (
            <div className="banner banner-info">
              <AlertTriangle size={14} /> 尚未渲染：选择预设并点击「开始渲染」，任务完成后会自动出现 B 版本。
            </div>
          )}

          <div className="preview-tips">
            <span>
              <Play size={12} /> 建议先用 A/B 对比确认响度与闪避，再导出成片。
            </span>
            <button type="button" className="link-btn" onClick={() => void load()}>
              <RefreshCw size={12} /> 刷新输出
            </button>
            <a className="link-btn" href="#report" onClick={(event) => event.preventDefault()}>
              <ArrowUpRight size={12} /> 查看报告
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

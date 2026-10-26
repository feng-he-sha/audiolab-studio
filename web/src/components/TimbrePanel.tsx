/** 音色 tab: SVG PCA scatter + cluster cards with rename / merge / preview. */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Check,
  GitMerge,
  Pencil,
  Play,
  RefreshCw,
  Sparkles,
  X,
} from "lucide-react";
import { describeError } from "../api/client";
import type { TimbreCluster, TimbreResult } from "../api/types";
import { useStudio } from "../state/StudioContext";
import { useToast } from "../state/ui";
import { formatNumber } from "../utils/format";
import { Chip, EmptyState, LoadingBlock } from "./common/ui";

const FALLBACK_COLORS = ["#38bdf8", "#f472b6", "#a78bfa", "#34d399", "#fbbf24", "#fb7185"];

const SCATTER_W = 620;
const SCATTER_H = 320;
const PAD = 36;

function clusterColor(cluster: TimbreCluster, index: number): string {
  return cluster.color || FALLBACK_COLORS[index % FALLBACK_COLORS.length];
}

export function TimbrePanel(): ReactNode {
  const { client, demo, selectedProject, dataVersion, toast } = useStudio();
  const projectId = selectedProject?.id ?? "";
  const [timbre, setTimbre] = useState<TimbreResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const value = await client.timbre(projectId);
      setTimbre(value);
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

  useEffect(
    () => () => {
      audioRef.current?.pause();
      audioRef.current = null;
    },
    [],
  );

  const bounds = useMemo(() => {
    const points = timbre?.points ?? [];
    if (points.length === 0) return { minX: -1, maxX: 1, minY: -1, maxY: 1 };
    const xs = points.map((point) => point.x);
    const ys = points.map((point) => point.y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    return {
      minX: minX === maxX ? minX - 1 : minX,
      maxX: minX === maxX ? maxX + 1 : maxX,
      minY: minY === maxY ? minY - 1 : minY,
      maxY: minY === maxY ? maxY + 1 : maxY,
    };
  }, [timbre]);

  const projectPoint = (x: number, y: number): { px: number; py: number } => ({
    px: PAD + ((x - bounds.minX) / (bounds.maxX - bounds.minX)) * (SCATTER_W - PAD * 2),
    py: SCATTER_H - PAD - ((y - bounds.minY) / (bounds.maxY - bounds.minY)) * (SCATTER_H - PAD * 2),
  });

  const playUrl = (url: string, label: string) => {
    if (demo) {
      toast.warn("演示模式没有音频文件，试听不可用。");
      return;
    }
    if (!url) {
      toast.warn("缺少片段音频地址。");
      return;
    }
    audioRef.current?.pause();
    const audio = new Audio(url);
    audioRef.current = audio;
    audio.play().catch((err: unknown) => toast.error(`试听失败：${describeError(err)}`));
    toast.info(`试听：${label}`);
  };

  const playRepresentative = (cluster: TimbreCluster) => {
    const clip =
      cluster.clips.find((item) => item.is_representative) ?? cluster.clips[0];
    if (!clip) {
      toast.warn(`簇「${cluster.label}」没有可用片段`);
      return;
    }
    playUrl(clip.url, cluster.user_label ?? cluster.label);
  };

  const toggleSelect = (clusterId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(clusterId)) next.delete(clusterId);
      else next.add(clusterId);
      return next;
    });
  };

  const startRename = (cluster: TimbreCluster) => {
    setEditingId(cluster.id);
    setEditValue(cluster.user_label ?? cluster.label);
  };

  const submitRename = async (cluster: TimbreCluster) => {
    if (!timbre) return;
    const value = editValue.trim();
    if (!value) {
      toast.warn("名称不能为空");
      return;
    }
    setBusy(true);
    try {
      const next = await client.setClusterLabel(cluster.id, value);
      setTimbre(next);
      setEditingId(null);
      toast.success("已重命名音色簇");
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  const mergeSelected = async () => {
    if (!timbre) return;
    const clusterIds = Array.from(selected);
    if (clusterIds.length < 2) {
      toast.warn("请至少勾选两个音色簇再合并。");
      return;
    }
    setBusy(true);
    try {
      const next = await client.mergeClusters(projectId, clusterIds);
      setTimbre(next);
      setSelected(new Set());
      toast.success(`已合并 ${clusterIds.length} 个音色簇`);
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  if (!projectId) return <EmptyState title="未选择项目" />;

  if (loading && !timbre) return <LoadingBlock label="正在加载音色聚类…" rows={3} />;

  if (error || !timbre) {
    return (
      <EmptyState
        icon={<AlertTriangle size={24} />}
        title="尚无音色聚类"
        description={error || "完成分析后会展示 PCA 散点与音色簇。"}
        action={
          <button type="button" className="btn btn-sm" onClick={() => void load()}>
            <RefreshCw size={13} /> 刷新
          </button>
        }
      />
    );
  }

  const clusters = timbre.clusters;
  const colorByIndex = new Map(clusters.map((cluster, index) => [cluster.index, clusterColor(cluster, index)]));

  return (
    <div className="timbre-panel">
      <div className="timbre-toolbar">
        <div className="timbre-toolbar-left">
          <Chip tone="var(--accent)">
            {timbre.backend === "mfcc" ? "MFCC 回退聚类" : "ColorSplitter 嵌入"}
          </Chip>
          <span className="muted">{clusters.length} 个音色簇 · {timbre.points.length} 个片段点</span>
        </div>
        <div className="timbre-toolbar-right">
          {selected.size > 0 ? (
            <button type="button" className="btn btn-sm" onClick={() => void mergeSelected()} disabled={busy}>
              <GitMerge size={13} /> 合并所选（{selected.size}）
            </button>
          ) : (
            <span className="muted">勾选两个以上簇可合并</span>
          )}
          <button type="button" className="btn btn-sm" onClick={() => void load()}>
            <RefreshCw size={13} /> 刷新
          </button>
        </div>
      </div>

      {timbre.warnings.length > 0 ? (
        <div className="banner banner-warn">
          <AlertTriangle size={14} /> {timbre.warnings[0]}
        </div>
      ) : null}

      <div className="timbre-layout">
        <div className="card scatter-card">
          <div className="scatter-head">
            <div>
              <div className="scatter-title">音色嵌入 PCA 投影</div>
              <div className="muted">每个点是一个音色片段，颜色表示所属簇</div>
            </div>
            <Sparkles size={18} className="icon-muted" />
          </div>
          <svg
            className="scatter-svg"
            viewBox={`0 0 ${SCATTER_W} ${SCATTER_H}`}
            role="img"
            aria-label="音色 PCA 散点图"
          >
            <defs>
              <radialGradient id="scatter-bg" cx="50%" cy="50%" r="70%">
                <stop offset="0%" stopColor="#151d2b" />
                <stop offset="100%" stopColor="#0e131d" />
              </radialGradient>
            </defs>
            <rect x={0} y={0} width={SCATTER_W} height={SCATTER_H} rx={12} fill="url(#scatter-bg)" />
            {[0.25, 0.5, 0.75].map((ratio) => (
              <g key={ratio}>
                <line
                  x1={PAD}
                  y1={PAD + ratio * (SCATTER_H - PAD * 2)}
                  x2={SCATTER_W - PAD}
                  y2={PAD + ratio * (SCATTER_H - PAD * 2)}
                  stroke="rgba(139,155,180,0.1)"
                />
                <line
                  x1={PAD + ratio * (SCATTER_W - PAD * 2)}
                  y1={PAD}
                  x2={PAD + ratio * (SCATTER_W - PAD * 2)}
                  y2={SCATTER_H - PAD}
                  stroke="rgba(139,155,180,0.1)"
                />
              </g>
            ))}
            <text x={SCATTER_W / 2} y={SCATTER_H - 8} textAnchor="middle" className="scatter-axis">
              PCA-1
            </text>
            <text x={12} y={SCATTER_H / 2} textAnchor="middle" className="scatter-axis" transform={`rotate(-90 12 ${SCATTER_H / 2})`}>
              PCA-2
            </text>
            {timbre.points.map((point, index) => {
              const { px, py } = projectPoint(point.x, point.y);
              const color = colorByIndex.get(point.cluster) ?? "#94a3b8";
              const cluster = clusters.find((item) => item.index === point.cluster);
              const isSelected = cluster ? selected.has(cluster.id) : false;
              return (
                <circle
                  key={`${point.clip_id ?? index}`}
                  cx={px}
                  cy={py}
                  r={isSelected ? 7 : 5.5}
                  fill={color}
                  fillOpacity={0.85}
                  stroke={isSelected ? "#e6edf7" : color}
                  strokeWidth={isSelected ? 1.5 : 1}
                  strokeOpacity={0.5}
                >
                  <title>{`${cluster?.label ?? `簇 ${point.cluster}`} · ${point.clip_id ?? "片段"}`}</title>
                </circle>
              );
            })}
            {clusters.map((cluster, index) => {
              const clusterPoints = timbre.points.filter((point) => point.cluster === cluster.index);
              if (clusterPoints.length === 0) return null;
              const centerX =
                clusterPoints.reduce((sum, point) => sum + point.x, 0) / clusterPoints.length;
              const centerY =
                clusterPoints.reduce((sum, point) => sum + point.y, 0) / clusterPoints.length;
              const { px, py } = projectPoint(centerX, centerY);
              return (
                <text
                  key={cluster.id}
                  x={px}
                  y={py - 12}
                  textAnchor="middle"
                  className="scatter-cluster-label"
                  fill={clusterColor(cluster, index)}
                >
                  {cluster.user_label ?? cluster.label}
                </text>
              );
            })}
          </svg>
          <div className="scatter-legend">
            {clusters.map((cluster, index) => (
              <span key={cluster.id} className="scatter-legend-item">
                <span className="legend-dot" style={{ background: clusterColor(cluster, index) }} />
                {cluster.user_label ?? cluster.label}
              </span>
            ))}
          </div>
        </div>

        <div className="cluster-grid">
          {clusters.map((cluster, index) => {
            const color = clusterColor(cluster, index);
            const isEditing = editingId === cluster.id;
            const feature = cluster.features;
            return (
              <div
                key={cluster.id}
                className={`cluster-card${selected.has(cluster.id) ? " selected" : ""}`}
                style={{ ["--cluster-color" as string]: color }}
              >
                <div className="cluster-card-head">
                  <span className="cluster-color" style={{ background: color }} />
                  {isEditing ? (
                    <div className="cluster-rename">
                      <input
                        value={editValue}
                        onChange={(event) => setEditValue(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") void submitRename(cluster);
                          if (event.key === "Escape") setEditingId(null);
                        }}
                        autoFocus
                        aria-label="音色簇名称"
                      />
                      <button type="button" className="icon-btn" onClick={() => void submitRename(cluster)} disabled={busy} aria-label="保存名称">
                        <Check size={13} />
                      </button>
                      <button type="button" className="icon-btn" onClick={() => setEditingId(null)} aria-label="取消重命名">
                        <X size={13} />
                      </button>
                    </div>
                  ) : (
                    <>
                      <span className="cluster-label">{cluster.user_label ?? cluster.label}</span>
                      <button type="button" className="icon-btn" onClick={() => startRename(cluster)} title="重命名">
                        <Pencil size={12} />
                      </button>
                    </>
                  )}
                  <label className="cluster-select" title="选中以合并">
                    <input
                      type="checkbox"
                      checked={selected.has(cluster.id)}
                      onChange={() => toggleSelect(cluster.id)}
                      aria-label={`选择音色簇 ${cluster.label}`}
                    />
                  </label>
                </div>

                <div className="cluster-meta">
                  <span>{cluster.n_clips} 个片段</span>
                  <span>{formatNumber(cluster.total_duration, 1)}s</span>
                </div>

                <div className="cluster-features">
                  <div>
                    <span className="k">F0</span>
                    <span className="v">{formatNumber(feature.f0_median, 0)} Hz</span>
                  </div>
                  <div>
                    <span className="k">质心</span>
                    <span className="v">{formatNumber(feature.centroid_mean, 0)} Hz</span>
                  </div>
                  <div>
                    <span className="k">HNR</span>
                    <span className="v">{formatNumber(feature.harmonic_ratio, 2)}</span>
                  </div>
                  <div>
                    <span className="k">RMS</span>
                    <span className="v">{formatNumber(feature.rms_db, 1)} dB</span>
                  </div>
                </div>

                <div className="cluster-actions">
                  <button type="button" className="btn btn-xs" onClick={() => playRepresentative(cluster)}>
                    <Play size={12} /> 代表片段
                  </button>
                  <span className="muted cluster-rep-count">{cluster.representative.length} 个代表</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/** 时间轴 tab: canvas waveform, segment editing, label filters, re-fusion. */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Filter,
  Layers,
  Loader2,
  Maximize2,
  RefreshCw,
  SlidersHorizontal,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { describeError } from "../api/client";
import type { Artifact, Label, Peaks, Segment, Timeline } from "../api/types";
import type { TransportTrack } from "../audio/Transport";
import { useTransport } from "../audio/useTransport";
import { useStudio } from "../state/StudioContext";
import { useToast } from "../state/ui";
import {
  LABEL_HEX,
  LABEL_TEXT,
  formatSeconds,
  effectiveLabel,
} from "../utils/format";
import { useKeyboard } from "../utils/hooks";
import { EmptyState, LoadingBlock, Modal } from "./common/ui";
import { SegmentInspector } from "./SegmentInspector";
import { TimelineCanvas } from "./TimelineCanvas";
import { TransportBar } from "./TransportBar";

const LABELS: Label[] = ["vocals", "music", "vocals+music", "other"];

interface ViewRange {
  start: number;
  end: number;
}

export function TimelinePanel(): ReactNode {
  const { client, demo, selectedProject, dataVersion, toast } = useStudio();
  const projectId = selectedProject?.id ?? "";
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [peaks, setPeaks] = useState<Peaks | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [labelFilter, setLabelFilter] = useState<Record<Label, boolean>>({
    vocals: true,
    music: true,
    "vocals+music": true,
    other: true,
  });
  const [view, setView] = useState<ViewRange>({ start: 0, end: 1 });
  const [playhead, setPlayhead] = useState(0);
  const [busy, setBusy] = useState(false);
  const [refuseOpen, setRefuseOpen] = useState(false);
  const [refuseMinSegment, setRefuseMinSegment] = useState(0.5);
  const [refuseSmooth, setRefuseSmooth] = useState(5);
  const [refuseMinMusic, setRefuseMinMusic] = useState(0.35);

  const duration = timeline?.duration ?? selectedProject?.media?.duration ?? 0;

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError("");
    try {
      const value = await client.timeline(projectId);
      setTimeline(value);
      setSelectedIndex(null);
      setPlayhead(0);
      setView({ start: 0, end: Math.max(0.5, value.duration) });
      try {
        const response = await client.artifacts(projectId);
        setArtifacts(response.artifacts);
        const candidate =
          response.artifacts.find((item) => item.kind === "preview") ??
          response.artifacts.find((item) => item.kind === "original");
        if (candidate) {
          const value2 = await client.peaks(projectId, candidate.id);
          setPeaks(value2);
        } else {
          setPeaks(null);
        }
      } catch {
        setPeaks(null);
      }
    } catch (err) {
      setError(describeError(err));
    } finally {
      setLoading(false);
    }
  }, [client, projectId]);

  useEffect(() => {
    void load();
  }, [load, dataVersion]);

  const audioArtifact = useMemo(
    () =>
      artifacts.find((item) => item.kind === "preview") ??
      artifacts.find((item) => item.kind === "original") ??
      null,
    [artifacts],
  );

  const tracks: TransportTrack[] = useMemo(
    () =>
      audioArtifact
        ? [
            {
              id: "timeline",
              label: audioArtifact.label,
              url: demo ? "" : audioArtifact.url,
              color: "var(--accent)",
            },
          ]
        : [],
    [audioArtifact, demo],
  );

  const transportKey = `${projectId}:${duration.toFixed(2)}:${audioArtifact?.id ?? "none"}`;
  const { transport, snapshot, time } = useTransport(transportKey, tracks, {
    duration,
    simulated: demo,
    loop: false,
  });

  useEffect(() => {
    setPlayhead(time);
  }, [time]);

  const seek = useCallback(
    (value: number) => {
      const clamped = Math.max(0, Math.min(duration || value, value));
      setPlayhead(clamped);
      transport?.seek(clamped);
    },
    [duration, transport],
  );

  const span = Math.max(0.05, view.end - view.start);

  const applyZoom = useCallback(
    (nextSpan: number, anchor: number) => {
      const total = duration || 1;
      const clamped = Math.max(0.4, Math.min(total, nextSpan));
      let start = anchor - clamped / 2;
      if (start < 0) start = 0;
      let end = start + clamped;
      if (end > total) {
        end = total;
        start = Math.max(0, end - clamped);
      }
      setView({ start, end });
    },
    [duration],
  );

  const fitView = useCallback(() => {
    setView({ start: 0, end: Math.max(0.5, duration) });
  }, [duration]);

  // Keep the playhead visible while playing.
  useEffect(() => {
    if (!snapshot.playing) return;
    if (playhead < view.start || playhead > view.end) {
      applyZoom(span, playhead);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playhead, snapshot.playing]);

  const mutate = async (action: () => Promise<Timeline>, successMessage: string) => {
    setBusy(true);
    try {
      const next = await action();
      setTimeline(next);
      setView((current) => ({
        start: Math.min(current.start, next.duration),
        end: Math.min(Math.max(current.end, 0.5), next.duration),
      }));
      setSelectedIndex((current) =>
        current !== null && current >= next.segments.length ? next.segments.length - 1 : current,
      );
      toast.success(successMessage);
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  const segmentIdAt = (index: number): number => timeline?.segments[index]?.id ?? index;

  const changeLabel = (label: Label | null) => {
    if (!timeline || selectedIndex === null) return;
    void mutate(
      () => client.setSegmentLabel(projectId, segmentIdAt(selectedIndex), label),
      label ? `已改标为「${LABEL_TEXT[label]}」` : "已恢复自动标签",
    );
  };

  const mergeNext = () => {
    if (!timeline || selectedIndex === null) return;
    const current = timeline.segments[selectedIndex];
    const next = timeline.segments[selectedIndex + 1];
    if (!current || !next) {
      toast.warn("没有下一段可合并");
      return;
    }
    if (effectiveLabel(current) !== effectiveLabel(next)) {
      toast.warn("仅支持合并相邻且同标签的分段；可先修改标签。");
      return;
    }
    void mutate(
      () =>
        client.mergeSegments(projectId, [
          segmentIdAt(selectedIndex),
          segmentIdAt(selectedIndex + 1),
        ]),
      "已合并相邻分段",
    );
  };

  const splitAtPlayhead = () => {
    if (!timeline || selectedIndex === null) return;
    void mutate(
      () => client.splitSegment(projectId, segmentIdAt(selectedIndex), playhead),
      "已在播放头处切分",
    );
  };

  const submitRefuse = async () => {
    setBusy(true);
    try {
      await client.refuse(projectId, {
        min_segment: refuseMinSegment,
        smooth_frames: refuseSmooth,
        min_music: refuseMinMusic,
      });
      toast.info("已提交重新融合任务，完成后时间轴会自动刷新。");
      setRefuseOpen(false);
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  useKeyboard(
    (event) => {
      if (event.code === "Space") {
        event.preventDefault();
        transport?.toggle();
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        seek(playhead - (event.shiftKey ? 10 : 2));
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        seek(playhead + (event.shiftKey ? 10 : 2));
      } else if (event.key === "f" || event.key === "F") {
        fitView();
      } else if (["1", "2", "3", "4"].includes(event.key)) {
        const label = LABELS[Number(event.key) - 1];
        setLabelFilter((prev) => ({ ...prev, [label]: !prev[label] }));
      } else if (event.key === "Escape") {
        setSelectedIndex(null);
      }
    },
    Boolean(timeline) && !refuseOpen,
  );

  if (!projectId) {
    return <div className="panel-empty">请选择项目</div>;
  }

  if (loading && !timeline) {
    return (
      <div className="timeline-panel">
        <LoadingBlock label="正在加载时间轴与波形…" rows={4} />
      </div>
    );
  }

  if (error) {
    return (
      <EmptyState
        icon={<AlertTriangle size={24} />}
        title="时间轴不可用"
        description={error}
        action={
          <>
            <button type="button" className="btn btn-sm" onClick={() => void load()}>
              <RefreshCw size={13} /> 重试
            </button>
            {selectedProject && selectedProject.status === "imported" ? (
              <span className="muted">请先在顶部点击「一键分析」。</span>
            ) : null}
          </>
        }
      />
    );
  }

  if (!timeline) return null;

  const selectedSegment: Segment | null =
    selectedIndex !== null ? (timeline.segments[selectedIndex] ?? null) : null;

  const readyArtifact = Boolean(transport);
  const zoomPercent = duration > 0 ? Math.round((1 - span / duration) * 100) : 0;

  return (
    <div className="timeline-panel">
      <div className="timeline-toolbar">
        <div className="label-filters" role="group" aria-label="标签过滤">
          <Filter size={13} className="muted" />
          {LABELS.map((label, index) => (
            <button
              key={label}
              type="button"
              className={`label-filter${labelFilter[label] ? " active" : ""}`}
              style={{ ["--label-color" as string]: LABEL_HEX[label] }}
              onClick={() => setLabelFilter((prev) => ({ ...prev, [label]: !prev[label] }))}
              title={`${LABEL_TEXT[label]}（快捷键 ${index + 1}）`}
            >
              <span className="label-filter-dot" />
              {LABEL_TEXT[label]}
            </button>
          ))}
        </div>
        <div className="timeline-toolbar-right">
          <div className="zoom-group">
            <button type="button" className="icon-btn" title="缩小" onClick={() => applyZoom(span * 1.4, playhead)}>
              <ZoomOut size={14} />
            </button>
            <input
              className="zoom-slider"
              type="range"
              min={0}
              max={100}
              value={zoomPercent}
              onChange={(event) => {
                const ratio = Number(event.target.value);
                applyZoom(duration * (1 - ratio / 100), (view.start + view.end) / 2);
              }}
              aria-label="时间轴缩放"
            />
            <button type="button" className="icon-btn" title="放大" onClick={() => applyZoom(span * 0.7, playhead)}>
              <ZoomIn size={14} />
            </button>
            <button type="button" className="btn btn-xs" title="适应窗口（F）" onClick={fitView}>
              <Maximize2 size={12} /> 适配
            </button>
          </div>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => setRefuseOpen(true)}
            disabled={busy}
            title="调整参数后重新融合分段"
          >
            <SlidersHorizontal size={13} /> 重新融合
          </button>
        </div>
      </div>

      <TimelineCanvas
        peaks={peaks}
        segments={timeline.segments}
        duration={duration}
        viewStart={view.start}
        viewEnd={view.end}
        playhead={playhead}
        selectedIndex={selectedIndex}
        labelFilter={labelFilter}
        onSeek={seek}
        onSelectSegment={setSelectedIndex}
        onZoom={(factor, anchor) => applyZoom(span * factor, anchor)}
        peaksMessage={audioArtifact ? "波形加载中（后端 peaks 接口）…" : "尚无分离结果，波形不可用"}
      />

      <TransportBar transport={transport} snapshot={snapshot} time={playhead} tracks={tracks} />

      <div className="timeline-summary">
        <span className="timeline-summary-item">
          <Layers size={13} /> {timeline.segments.length} 个分段
        </span>
        {LABELS.map((label) => (
          <span key={label} className="timeline-summary-item">
            <span className="label-filter-dot" style={{ background: LABEL_HEX[label] }} />
            {LABEL_TEXT[label]} {(timeline.summary[label] ?? 0).toFixed(1)}s
          </span>
        ))}
        <span className="timeline-summary-hint">
          点击定位 / 点击分段选中 · Ctrl+滚轮缩放 · 空格播放 · ←/→ 快移
        </span>
      </div>

      {timeline.warnings.length > 0 ? (
        <div className="timeline-warnings">
          {timeline.warnings.map((warning) => (
            <div key={warning} className="timeline-warning">
              <AlertTriangle size={13} /> {warning}
            </div>
          ))}
        </div>
      ) : null}

      {selectedSegment && selectedIndex !== null ? (
        <SegmentInspector
          segment={selectedSegment}
          index={selectedIndex}
          playhead={playhead}
          busy={busy || !readyArtifact}
          onChangeLabel={changeLabel}
          onMergeNext={mergeNext}
          onSplitAtPlayhead={splitAtPlayhead}
          onPlaySegment={() => {
            seek(selectedSegment.start + 0.05);
            void transport?.play();
          }}
          onClose={() => setSelectedIndex(null)}
        />
      ) : (
        <div className="timeline-hint">
          点击上方波形中的彩色分段查看详情：改标签、合并、切分、恢复自动。
        </div>
      )}

      <Modal
        open={refuseOpen}
        title="重新融合分段"
        onClose={() => setRefuseOpen(false)}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setRefuseOpen(false)}>
              取消
            </button>
            <button type="button" className="btn btn-primary" onClick={() => void submitRefuse()} disabled={busy}>
              {busy ? <Loader2 size={14} className="spin" /> : <Layers size={14} />} 重新融合
            </button>
          </>
        }
      >
        <p className="muted modal-hint">
          调整融合参数后重新生成时间轴，会覆盖当前自动分段（手动改标签保留在 user_label 中）。
        </p>
        <div className="param-grid">
          <label className="field">
            <span className="field-label">最短段（秒）</span>
            <input
              type="number"
              min={0.1}
              max={10}
              step={0.1}
              value={refuseMinSegment}
              onChange={(event) => setRefuseMinSegment(Number(event.target.value))}
            />
            <span className="field-hint">短于该值的分段会并入相邻段</span>
          </label>
          <label className="field">
            <span className="field-label">平滑帧数</span>
            <input
              type="number"
              min={1}
              max={50}
              step={1}
              value={refuseSmooth}
              onChange={(event) => setRefuseSmooth(Number(event.target.value))}
            />
            <span className="field-hint">多数投票窗口（20ms/帧）</span>
          </label>
          <label className="field">
            <span className="field-label">音乐门限</span>
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={refuseMinMusic}
              onChange={(event) => setRefuseMinMusic(Number(event.target.value))}
            />
            <span className="field-hint">低于该音乐概率归为人声</span>
          </label>
        </div>
        <div className="muted modal-hint">
          当前播放头：{formatSeconds(playhead)} / {formatSeconds(duration)}
        </div>
      </Modal>
    </div>
  );
}

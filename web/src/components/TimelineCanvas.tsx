/** Canvas waveform + colored segment overlay + ruler + playhead. */
import { useEffect, useRef, useState, type PointerEvent, type ReactNode, type WheelEvent } from "react";
import type { Label, Peaks, Segment } from "../api/types";
import { LABEL_HEX, LABEL_TEXT, effectiveLabel, formatSeconds } from "../utils/format";
import { useElementSize } from "../utils/hooks";

export interface TimelineCanvasProps {
  peaks: Peaks | null;
  segments: Segment[];
  duration: number;
  viewStart: number;
  viewEnd: number;
  playhead: number;
  selectedIndex: number | null;
  labelFilter: Record<Label, boolean>;
  onSeek: (time: number) => void;
  onSelectSegment: (index: number | null) => void;
  onZoom: (factor: number, anchor: number) => void;
  peaksMessage?: string;
}

const RULER_HEIGHT = 24;
const BAND_HEIGHT = 26;
const SEGMENT_ALPHA = 0.16;
const COLORS = {
  bg: "#0e131d",
  ruler: "#8b9bb4",
  grid: "rgba(139,155,180,0.12)",
  wave: "#5eead4",
  waveSoft: "rgba(94,234,212,0.18)",
  playhead: "#f87171",
  selection: "#e6edf7",
  muted: "#8b9bb4",
};

function niceStep(spanSeconds: number, width: number): number {
  const targetPx = 90;
  const raw = (spanSeconds / Math.max(1, width)) * targetPx;
  const steps = [0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800];
  for (const step of steps) {
    if (step >= raw) return step;
  }
  return 3600;
}

export function TimelineCanvas({
  peaks,
  segments,
  duration,
  viewStart,
  viewEnd,
  playhead,
  selectedIndex,
  labelFilter,
  onSeek,
  onSelectSegment,
  onZoom,
  peaksMessage,
}: TimelineCanvasProps): ReactNode {
  const [ref, size] = useElementSize<HTMLDivElement>();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const dragging = useRef(false);

  const width = Math.max(1, size.width);
  const height = Math.max(120, size.height || 200);
  const span = Math.max(0.05, viewEnd - viewStart);

  const timeAt = (clientX: number): number => {
    const canvas = canvasRef.current;
    if (!canvas) return viewStart;
    const rect = canvas.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / Math.max(1, rect.width)));
    return viewStart + ratio * span;
  };

  const segmentAt = (time: number): number | null => {
    for (let index = segments.length - 1; index >= 0; index -= 1) {
      const segment = segments[index];
      if (time >= segment.start && time <= segment.stop) return index;
    }
    return null;
  };

  const seekFrom = (clientX: number, selectSegment: boolean) => {
    const time = timeAt(clientX);
    onSeek(time);
    if (selectSegment) onSelectSegment(segmentAt(time));
  };

  const onPointerDown = (event: PointerEvent<HTMLCanvasElement>) => {
    if (event.button !== 0) return;
    dragging.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    seekFrom(event.clientX, true);
  };

  const onPointerMove = (event: PointerEvent<HTMLCanvasElement>) => {
    setHover(timeAt(event.clientX));
    if (dragging.current) seekFrom(event.clientX, false);
  };

  const onPointerUp = (event: PointerEvent<HTMLCanvasElement>) => {
    dragging.current = false;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const onWheel = (event: WheelEvent<HTMLCanvasElement>) => {
    event.preventDefault();
    const anchor = timeAt(event.clientX);
    onZoom(event.deltaY > 0 ? 1.28 : 0.78, anchor);
  };

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    // Background
    ctx.fillStyle = COLORS.bg;
    ctx.fillRect(0, 0, width, height);

    const waveTop = RULER_HEIGHT;
    const waveBottom = height - BAND_HEIGHT;
    const mid = (waveTop + waveBottom) / 2;
    const amplitude = (waveBottom - waveTop) / 2 - 4;
    const toX = (time: number) => ((time - viewStart) / span) * width;

    // Ruler + vertical grid
    const step = niceStep(span, width);
    const first = Math.ceil(viewStart / step) * step;
    ctx.font = "10px 'Segoe UI', 'Microsoft YaHei UI', system-ui, sans-serif";
    ctx.textBaseline = "middle";
    for (let time = first; time <= viewEnd; time += step) {
      const x = toX(time);
      ctx.strokeStyle = COLORS.grid;
      ctx.beginPath();
      ctx.moveTo(x, RULER_HEIGHT);
      ctx.lineTo(x, height - BAND_HEIGHT);
      ctx.stroke();
      ctx.fillStyle = COLORS.ruler;
      const label = step < 1 ? `${time.toFixed(1)}s` : formatSeconds(time, false);
      ctx.fillText(label, Math.min(width - 34, Math.max(2, x + 4)), RULER_HEIGHT / 2);
    }

    // Segment overlays on the waveform area
    segments.forEach((segment, index) => {
      if (segment.stop < viewStart || segment.start > viewEnd) return;
      const label = effectiveLabel(segment);
      const enabled = labelFilter[label];
      const x1 = Math.max(0, toX(segment.start));
      const x2 = Math.min(width, toX(segment.stop));
      if (x2 <= x1) return;
      ctx.fillStyle = enabled ? `${LABEL_HEX[label]}22` : "rgba(139,155,180,0.06)";
      ctx.fillRect(x1, waveTop, x2 - x1, waveBottom - waveTop);
      if (index === selectedIndex) {
        ctx.strokeStyle = COLORS.selection;
        ctx.lineWidth = 1.5;
        ctx.strokeRect(x1 + 0.5, waveTop + 0.5, Math.max(1, x2 - x1 - 1), waveBottom - waveTop - 1);
      }
    });

    // Waveform
    if (peaks && peaks.peaks.length > 0) {
      const all = peaks.peaks;
      const count = all.length;
      const samples = Math.min(width, 1600);
      ctx.beginPath();
      for (let x = 0; x < width; x += 1) {
        const time = viewStart + (x / width) * span;
        if (time < 0 || time > peaks.duration) continue;
        const startIndex = Math.floor((time / Math.max(0.001, peaks.duration)) * count);
        const endIndex = Math.max(
          startIndex + 1,
          Math.floor(((time + span / width) / Math.max(0.001, peaks.duration)) * count),
        );
        let min = 0;
        let max = 0;
        for (let i = startIndex; i < endIndex && i < count; i += 1) {
          const [lo, hi] = all[i];
          if (lo < min) min = lo;
          if (hi > max) max = hi;
        }
        const y1 = mid - max * amplitude;
        const y2 = mid - min * amplitude;
        ctx.moveTo(x + 0.5, y1);
        ctx.lineTo(x + 0.5, Math.max(y1 + 0.6, y2));
      }
      ctx.strokeStyle = COLORS.wave;
      ctx.lineWidth = 1;
      ctx.stroke();

      // Soft mirror glow
      ctx.fillStyle = COLORS.waveSoft;
      ctx.beginPath();
      ctx.moveTo(0, mid);
      for (let x = 0; x < width; x += 2) {
        const index = Math.floor(((viewStart + (x / width) * span) / Math.max(0.001, peaks.duration)) * count);
        const value = Math.abs(all[Math.min(count - 1, Math.max(0, index))]?.[1] ?? 0);
        ctx.lineTo(x, mid - value * amplitude);
      }
      for (let x = width; x >= 0; x -= 2) {
        const index = Math.floor(((viewStart + (x / width) * span) / Math.max(0.001, peaks.duration)) * count);
        const value = Math.abs(all[Math.min(count - 1, Math.max(0, index))]?.[0] ?? 0);
        ctx.lineTo(x, mid + value * amplitude);
      }
      ctx.closePath();
      ctx.fill();
      void samples;
    } else {
      ctx.fillStyle = COLORS.muted;
      ctx.font = "12px 'Segoe UI', 'Microsoft YaHei UI', system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(peaksMessage ?? "波形加载中…", width / 2, mid);
      ctx.textAlign = "left";
    }

    // Segment color band + labels
    const bandTop = height - BAND_HEIGHT;
    ctx.fillStyle = "rgba(10,14,22,0.65)";
    ctx.fillRect(0, bandTop, width, BAND_HEIGHT);
    segments.forEach((segment, index) => {
      if (segment.stop < viewStart || segment.start > viewEnd) return;
      const label = effectiveLabel(segment);
      const enabled = labelFilter[label];
      const x1 = Math.max(0, toX(segment.start));
      const x2 = Math.min(width, toX(segment.stop));
      if (x2 <= x1) return;
      ctx.globalAlpha = enabled ? 0.9 : 0.18;
      ctx.fillStyle = LABEL_HEX[label];
      ctx.fillRect(x1 + 0.5, bandTop + 3, Math.max(1, x2 - x1 - 1), BAND_HEIGHT - 6);
      ctx.globalAlpha = 1;
      if (index === selectedIndex) {
        ctx.strokeStyle = COLORS.selection;
        ctx.lineWidth = 1.5;
        ctx.strokeRect(x1 + 0.5, bandTop + 2.5, Math.max(1, x2 - x1 - 1), BAND_HEIGHT - 5);
      }
      const text = `${segment.user_label ? "★" : ""}${LABEL_TEXT[label]} ${Math.round(segment.confidence * 100)}%`;
      if (x2 - x1 > 64 && enabled) {
        ctx.fillStyle = "#0b0e14";
        ctx.font = "10px 'Segoe UI', 'Microsoft YaHei UI', system-ui, sans-serif";
        ctx.fillText(text, x1 + 5, bandTop + BAND_HEIGHT / 2);
      }
    });

    // Hover line
    if (hover !== null && hover >= viewStart && hover <= viewEnd) {
      const x = toX(hover);
      ctx.strokeStyle = "rgba(230,237,247,0.35)";
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(x, RULER_HEIGHT);
      ctx.lineTo(x, bandTop);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(18,23,34,0.95)";
      const label = formatSeconds(hover);
      const labelWidth = ctx.measureText(label).width + 12;
      const labelX = Math.min(width - labelWidth, Math.max(0, x - labelWidth / 2));
      ctx.fillRect(labelX, 2, labelWidth, 18);
      ctx.fillStyle = "#e6edf7";
      ctx.fillText(label, labelX + 6, 11);
    }

    // Playhead
    if (playhead >= viewStart - 0.1 && playhead <= viewEnd + 0.1) {
      const x = Math.max(0, Math.min(width, toX(playhead)));
      ctx.strokeStyle = COLORS.playhead;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
      ctx.fillStyle = COLORS.playhead;
      ctx.beginPath();
      ctx.moveTo(x - 5, 0);
      ctx.lineTo(x + 5, 0);
      ctx.lineTo(x, 8);
      ctx.closePath();
      ctx.fill();
    }

    // Duration edge label
    ctx.fillStyle = "rgba(139,155,180,0.65)";
    ctx.font = "10px 'Segoe UI', system-ui, sans-serif";
    ctx.textAlign = "right";
    ctx.fillText(`视窗 ${formatSeconds(span)} / ${formatSeconds(duration)}`, width - 6, height - 4);
    ctx.textAlign = "left";
  }, [peaks, segments, duration, viewStart, viewEnd, span, width, height, playhead, selectedIndex, labelFilter, hover, peaksMessage]);

  return (
    <div className="timeline-canvas-wrap" ref={ref}>
      <canvas
        ref={canvasRef}
        className="timeline-canvas"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onPointerLeave={() => setHover(null)}
        onWheel={onWheel}
        aria-label="时间轴波形，点击定位播放头，点击分段选中"
        role="img"
      />
    </div>
  );
}

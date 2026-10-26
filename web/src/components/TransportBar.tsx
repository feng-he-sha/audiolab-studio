/** Shared transport controls: play/pause, time, loop + per-stem mix strips. */
import type { ReactNode } from "react";
import {
  AlertTriangle,
  Headphones,
  Loader2,
  Pause,
  Play,
  Repeat,
  Volume1,
  Volume2,
  VolumeX,
} from "lucide-react";
import type { Transport, TransportSnapshot, TransportTrack } from "../audio/Transport";
import { formatSeconds } from "../utils/format";

export interface TransportBarProps {
  transport: Transport | null;
  snapshot: TransportSnapshot;
  time: number;
  tracks?: TransportTrack[];
  showTracks?: boolean;
  onError?: (message: string) => void;
}

export function TransportBar({
  transport,
  snapshot,
  time,
  tracks = [],
  showTracks = false,
  onError,
}: TransportBarProps): ReactNode {
  const disabled = !transport || snapshot.mode === "error" || snapshot.mode === "loading";
  const duration = snapshot.duration || 0;

  const playPause = () => {
    if (!transport) return;
    if (snapshot.playing) transport.pause();
    else void transport.play();
  };

  return (
    <div className="transport">
      <div className="transport-main">
        <button
          type="button"
          className={`transport-play${snapshot.playing ? " playing" : ""}`}
          onClick={playPause}
          disabled={disabled}
          title={snapshot.playing ? "暂停（空格）" : "播放（空格）"}
        >
          {snapshot.loading ? (
            <Loader2 size={18} className="spin" />
          ) : snapshot.playing ? (
            <Pause size={18} />
          ) : (
            <Play size={18} />
          )}
        </button>
        <div className="transport-time">
          <span className="transport-current">{formatSeconds(time)}</span>
          <span className="transport-sep">/</span>
          <span className="transport-duration">{formatSeconds(duration)}</span>
        </div>
        <div className="transport-progress" aria-hidden="true">
          <div
            className="transport-progress-fill"
            style={{ width: duration > 0 ? `${Math.min(100, (time / duration) * 100)}%` : "0%" }}
          />
        </div>
        <button
          type="button"
          className={`icon-btn${snapshot.loop ? " active" : ""}`}
          title="循环播放"
          onClick={() => transport?.setLoop(!snapshot.loop)}
          disabled={!transport}
        >
          <Repeat size={15} />
        </button>
        <span className={`transport-mode mode-${snapshot.mode}`}>
          {snapshot.mode === "webaudio"
            ? "Web Audio · 多轨同步"
            : snapshot.mode === "element"
              ? "HTML5 Audio"
              : snapshot.mode === "simulated"
                ? "演示播放"
                : snapshot.mode === "loading"
                  ? "加载音频…"
                  : snapshot.mode === "error"
                    ? "音频不可用"
                    : "空闲"}
        </span>
      </div>

      {snapshot.error ? (
        <div className="transport-error" role="status">
          <AlertTriangle size={13} /> {snapshot.error}
          {onError ? (
            <button type="button" className="link-btn" onClick={() => onError(snapshot.error)}>
              详情
            </button>
          ) : null}
        </div>
      ) : null}

      {showTracks && tracks.length > 0 ? (
        <div className="transport-tracks">
          {tracks.map((track) => {
            const mix = transport?.getMix(track.id) ?? { gain: 0.9, mute: false, solo: false };
            const VolumeIcon = mix.mute ? VolumeX : mix.gain < 0.5 ? Volume1 : Volume2;
            return (
              <div className="track-strip" key={track.id}>
                <span className="track-swatch" style={{ background: track.color ?? "var(--accent)" }} />
                <span className="track-label">{track.label}</span>
                <button
                  type="button"
                  className={`icon-btn track-btn${mix.mute ? " active-danger" : ""}`}
                  title="静音"
                  onClick={() => transport?.setMix(track.id, { mute: !mix.mute })}
                  disabled={!transport}
                >
                  <VolumeIcon size={14} />
                </button>
                <button
                  type="button"
                  className={`track-solo${mix.solo ? " active" : ""}`}
                  title="独奏"
                  onClick={() => transport?.setMix(track.id, { solo: !mix.solo })}
                  disabled={!transport}
                >
                  S
                </button>
                <input
                  className="track-volume"
                  type="range"
                  min={0}
                  max={130}
                  value={Math.round(mix.gain * 100)}
                  onChange={(event) => transport?.setGain(track.id, Number(event.target.value) / 100)}
                  disabled={!transport}
                  aria-label={`${track.label} 音量`}
                />
                <span className="track-gain">{Math.round(mix.gain * 100)}</span>
              </div>
            );
          })}
        </div>
      ) : null}

      {!showTracks && tracks.length > 0 ? (
        <div className="transport-tracks-inline">
          <Headphones size={12} /> 轨道：{tracks.map((track) => track.label).join(" / ")}
        </div>
      ) : null}
    </div>
  );
}

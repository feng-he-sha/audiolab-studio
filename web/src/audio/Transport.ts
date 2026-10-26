/**
 * Audio playback engine.
 *
 * Primary mode uses the Web Audio API: every stem is decoded once, gets its
 * own GainNode and is started at the same AudioContext time so stems stay in
 * sample-accurate sync while solo/mute/volume are mixed live.
 *
 * Fallbacks:
 *  - `element`   — a single <audio> element (decode failure or > 10 min file).
 *  - `simulated` — demo mode, no audio file required; the playhead still moves.
 */

export interface TransportTrack {
  id: string;
  label: string;
  url: string;
  color?: string;
  kind?: string;
}

export interface MixState {
  gain: number;
  mute: boolean;
  solo: boolean;
}

export type TransportMode =
  | "idle"
  | "loading"
  | "webaudio"
  | "element"
  | "simulated"
  | "error";

export interface TransportSnapshot {
  mode: TransportMode;
  playing: boolean;
  duration: number;
  time: number;
  loop: boolean;
  ready: boolean;
  error: string;
  loading: boolean;
}

export interface TransportInit {
  /** Known media duration in seconds (authoritative over decoded buffers). */
  duration?: number;
  loop?: boolean;
  /** Demo mode: no network/decode, clock-driven playback. */
  simulated?: boolean;
  /** Decoded audio longer than this uses the <audio> fallback. Default 600s. */
  fallbackAfter?: number;
}

const DEFAULT_MIX: MixState = { gain: 0.9, mute: false, solo: false };

function errorText(err: unknown): string {
  if (err instanceof DOMException && err.name === "NotSupportedError") {
    return "浏览器无法解码该音频格式，已切换为 <audio> 播放。";
  }
  if (err instanceof Error) return err.message;
  return String(err);
}

export class Transport {
  private tracks: TransportTrack[] = [];
  private mix = new Map<string, MixState>();
  private init: TransportInit;

  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private buffers = new Map<string, AudioBuffer>();
  private gainNodes = new Map<string, GainNode>();
  private sources = new Map<string, AudioBufferSourceNode>();

  private element: HTMLAudioElement | null = null;
  private primaryId = "";

  private duration = 0;
  private offset = 0;
  private playing = false;
  private loop = false;
  private mode: TransportMode = "idle";
  private error = "";
  private ready = false;
  private loading = false;
  private disposed = false;

  private playStartedAt = 0;
  private simulatedStart = 0;
  private raf = 0;

  private stateListeners = new Set<(snapshot: TransportSnapshot) => void>();
  private timeListeners = new Set<(time: number) => void>();

  constructor(init: TransportInit = {}) {
    this.init = init;
    this.duration = Math.max(0, init.duration ?? 0);
    this.loop = init.loop ?? false;
  }

  /* ------------------------------------------------------------ */
  /* Loading                                                      */
  /* ------------------------------------------------------------ */

  async load(tracks: TransportTrack[]): Promise<void> {
    this.tracks = tracks.filter((t) => t.id);
    this.primaryId = this.tracks[0]?.id ?? "";
    for (const track of this.tracks) {
      if (!this.mix.has(track.id)) this.mix.set(track.id, { ...DEFAULT_MIX });
    }
    if (this.disposed) return;

    if (this.init.simulated) {
      this.mode = "simulated";
      this.ready = true;
      if (!this.duration) this.duration = 30;
      this.emitState();
      return;
    }

    const playable = this.tracks.filter((t) => t.url);
    if (playable.length === 0) {
      this.mode = "error";
      this.error = "没有可播放的音频：后端尚未生成 artifacts（预览/分离结果）。";
      this.ready = true;
      this.emitState();
      return;
    }

    this.loading = true;
    this.mode = "loading";
    this.emitState();

    // Decode everything in parallel; if a single stem fails we still try the
    // remaining ones, and if all fail we fall back to an <audio> element.
    const ctx = this.getContext();
    if (!ctx) {
      await this.useElementFallback("当前浏览器不支持 Web Audio，使用 <audio> 播放。");
      return;
    }

    const results = await Promise.allSettled(
      playable.map(async (track) => {
        const controller = new AbortController();
        const timer = window.setTimeout(() => controller.abort(), 20000);
        try {
          const response = await fetch(track.url, { signal: controller.signal });
          if (!response.ok) throw new Error(`加载失败（HTTP ${response.status}）：${track.label}`);
          const data = await response.arrayBuffer();
          const buffer = await ctx.decodeAudioData(data);
          return { track, buffer };
        } finally {
          window.clearTimeout(timer);
        }
      }),
    );

    if (this.disposed) return;

    const decoded: { track: TransportTrack; buffer: AudioBuffer }[] = [];
    const failures: string[] = [];
    results.forEach((result, index) => {
      if (result.status === "fulfilled") {
        decoded.push(result.value);
      } else {
        failures.push(`${playable[index].label}：${errorText(result.reason)}`);
      }
    });

    if (decoded.length === 0) {
      await this.useElementFallback(
        failures[0] ?? "Web Audio 解码失败，使用 <audio> 播放。",
      );
      return;
    }

    const decodedDuration = Math.max(...decoded.map((d) => d.buffer.duration));
    const fallbackAfter = this.init.fallbackAfter ?? 600;
    if (decodedDuration > fallbackAfter) {
      await this.useElementFallback(
        `音频超过 ${Math.round(fallbackAfter / 60)} 分钟，使用 <audio> 元素播放以节省内存。`,
      );
      return;
    }

    this.master = ctx.createGain();
    this.master.gain.value = 1;
    this.master.connect(ctx.destination);

    for (const { track, buffer } of decoded) {
      this.buffers.set(track.id, buffer);
      const gain = ctx.createGain();
      gain.gain.value = this.effectiveGain(track.id);
      gain.connect(this.master);
      this.gainNodes.set(track.id, gain);
    }

    if (!this.duration) this.duration = decodedDuration;
    this.mode = "webaudio";
    this.ready = true;
    this.loading = false;
    this.error = failures.length > 0 ? `部分音轨解码失败：${failures[0]}` : "";
    this.emitState();
  }

  private getContext(): AudioContext | null {
    if (this.ctx) return this.ctx;
    const Ctor =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return null;
    try {
      this.ctx = new Ctor();
      return this.ctx;
    } catch {
      return null;
    }
  }

  private async useElementFallback(reason: string): Promise<void> {
    const primary = this.tracks.find((t) => t.url);
    if (!primary) {
      this.mode = "error";
      this.error = "没有可播放的音频。";
      this.loading = false;
      this.ready = true;
      this.emitState();
      return;
    }
    this.releaseAudioGraph();
    this.primaryId = primary.id;
    this.mode = "element";
    this.error = reason;
    this.loading = false;
    this.ready = true;

    const audio = new Audio();
    audio.preload = "metadata";
    audio.src = primary.url;
    audio.loop = false;
    audio.volume = this.effectiveGain(primary.id);
    this.element = audio;
    audio.addEventListener("loadedmetadata", () => {
      if (this.disposed) return;
      if (!this.duration && Number.isFinite(audio.duration)) this.duration = audio.duration;
      this.emitState();
    });
    audio.addEventListener("error", () => {
      if (this.disposed) return;
      this.error = `音频加载失败：${primary.url}`;
      this.mode = "error";
      this.ready = true;
      this.emitState();
    });
    audio.addEventListener("ended", () => {
      if (this.loop) {
        audio.currentTime = 0;
        void audio.play().catch(() => undefined);
      } else {
        this.offset = this.duration;
        this.playing = false;
        this.stopTick();
        this.emitState();
        this.emitTime(this.offset);
      }
    });
    this.emitState();
  }

  /* ------------------------------------------------------------ */
  /* Playback                                                     */
  /* ------------------------------------------------------------ */

  async play(): Promise<void> {
    if (this.playing || this.disposed || this.mode === "error") return;
    if (this.mode === "simulated") {
      if (this.duration > 0 && this.offset >= this.duration - 0.02) this.offset = 0;
      this.simulatedStart = performance.now();
      this.playing = true;
      this.emitState();
      this.startTick();
      return;
    }

    if (this.mode === "webaudio") {
      const ctx = this.ctx;
      if (!ctx) return;
      try {
        await ctx.resume();
      } catch {
        /* ignore */
      }
      if (this.duration > 0 && this.offset >= this.duration - 0.02) this.offset = 0;
      this.startSources();
      this.playing = true;
      this.emitState();
      this.startTick();
      return;
    }

    if (this.mode === "element" && this.element) {
      const audio = this.element;
      if (this.duration > 0 && audio.currentTime >= this.duration - 0.05) audio.currentTime = 0;
      try {
        await audio.play();
        this.playing = true;
        this.emitState();
        this.startTick();
      } catch (err) {
        this.error = `播放失败：${errorText(err)}`;
        this.emitState();
      }
    }
  }

  pause(): void {
    if (!this.playing) return;
    if (this.mode === "webaudio") this.offset = this.currentTime();
    else if (this.mode === "element" && this.element) this.offset = this.element.currentTime;
    else if (this.mode === "simulated") this.offset = this.currentTime();

    this.playing = false;
    this.stopTick();
    if (this.mode === "webaudio") this.stopSources();
    if (this.mode === "element" && this.element) this.element.pause();
    this.emitState();
    this.emitTime(this.offset);
  }

  toggle(): void {
    if (this.playing) this.pause();
    else void this.play();
  }

  seek(time: number): void {
    const target = Math.min(this.duration || Number.POSITIVE_INFINITY, Math.max(0, time));
    const wasPlaying = this.playing;
    if (this.mode === "webaudio") {
      const ctx = this.ctx;
      if (wasPlaying) {
        this.stopSources();
        this.playing = false;
        this.stopTick();
      }
      this.offset = target;
      if (wasPlaying && ctx) {
        this.startSources();
        this.playing = true;
        this.startTick();
      }
    } else if (this.mode === "element" && this.element) {
      this.element.currentTime = target;
      this.offset = target;
    } else {
      this.offset = target;
      if (wasPlaying) {
        this.simulatedStart = performance.now();
      }
    }
    this.emitState();
    this.emitTime(target);
  }

  setLoop(loop: boolean): void {
    this.loop = loop;
    if (this.element) this.element.loop = false;
    this.emitState();
  }

  /* ------------------------------------------------------------ */
  /* Mixing                                                       */
  /* ------------------------------------------------------------ */

  getMix(trackId: string): MixState {
    return this.mix.get(trackId) ?? { ...DEFAULT_MIX };
  }

  setMix(trackId: string, patch: Partial<MixState>): void {
    const current = this.mix.get(trackId) ?? { ...DEFAULT_MIX };
    const next: MixState = { ...current, ...patch };
    this.mix.set(trackId, next);
    this.applyMix();
    this.emitState();
  }

  setGain(trackId: string, gain: number): void {
    this.setMix(trackId, { gain: Math.max(0, Math.min(1.5, gain)) });
  }

  private effectiveGain(trackId: string): number {
    const anySolo = Array.from(this.mix.values()).some((m) => m.solo);
    const mix = this.mix.get(trackId) ?? DEFAULT_MIX;
    if (anySolo && !mix.solo) return 0;
    if (mix.mute && !mix.solo) return 0;
    return Math.max(0, Math.min(1.5, mix.gain));
  }

  private applyMix(): void {
    this.gainNodes.forEach((node, id) => {
      const ctx = this.ctx;
      const gain = this.effectiveGain(id);
      if (ctx) node.gain.setTargetAtTime(gain, ctx.currentTime, 0.015);
      else node.gain.value = gain;
    });
    if (this.element) this.element.volume = Math.min(1, this.effectiveGain(this.primaryId));
  }

  /* ------------------------------------------------------------ */
  /* Internal playback plumbing                                   */
  /* ------------------------------------------------------------ */

  private startSources(): void {
    const ctx = this.ctx;
    if (!ctx) return;
    this.stopSources();
    const startAt = ctx.currentTime + 0.03;
    this.playStartedAt = startAt;
    const from = this.offset;
    this.gainNodes.forEach((gain, id) => {
      const buffer = this.buffers.get(id);
      if (!buffer) return;
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(gain);
      gain.gain.value = this.effectiveGain(id);
      try {
        source.start(startAt, Math.min(from, Math.max(0, buffer.duration - 0.001)));
      } catch {
        return;
      }
      this.sources.set(id, source);
    });
  }

  private stopSources(): void {
    this.sources.forEach((source) => {
      try {
        source.onended = null;
        source.stop();
        source.disconnect();
      } catch {
        /* already stopped */
      }
    });
    this.sources.clear();
  }

  private releaseAudioGraph(): void {
    this.stopSources();
    this.gainNodes.forEach((node) => {
      try {
        node.disconnect();
      } catch {
        /* ignore */
      }
    });
    this.gainNodes.clear();
    this.buffers.clear();
    if (this.master) {
      try {
        this.master.disconnect();
      } catch {
        /* ignore */
      }
      this.master = null;
    }
    if (this.ctx && this.ctx.state !== "closed") {
      void this.ctx.close().catch(() => undefined);
    }
    this.ctx = null;
  }

  private startTick(): void {
    this.stopTick();
    const tick = () => {
      if (!this.playing || this.disposed) return;
      const time = this.currentTime();
      this.emitTime(time);
      if (this.duration > 0 && time >= this.duration - 0.03) {
        if (this.loop) {
          this.restart();
          return;
        }
        this.pause();
        this.offset = this.duration;
        this.emitTime(this.duration);
        return;
      }
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }

  private stopTick(): void {
    if (this.raf) {
      cancelAnimationFrame(this.raf);
      this.raf = 0;
    }
  }

  private restart(): void {
    if (this.mode === "webaudio") {
      this.offset = 0;
      this.startSources();
      this.playStartedAt = this.ctx ? this.ctx.currentTime + 0.03 : 0;
      this.startTick();
      return;
    }
    if (this.mode === "element" && this.element) {
      this.element.currentTime = 0;
      void this.element.play().catch(() => undefined);
      this.startTick();
      return;
    }
    if (this.mode === "simulated") {
      this.offset = 0;
      this.simulatedStart = performance.now();
      this.startTick();
    }
  }

  currentTime(): number {
    if (this.mode === "webaudio") {
      if (!this.playing) return this.offset;
      const ctx = this.ctx;
      if (!ctx) return this.offset;
      return this.offset + Math.max(0, ctx.currentTime - this.playStartedAt);
    }
    if (this.mode === "element" && this.element) return this.element.currentTime;
    if (this.mode === "simulated") {
      if (!this.playing) return this.offset;
      return this.offset + (performance.now() - this.simulatedStart) / 1000;
    }
    return this.offset;
  }

  /* ------------------------------------------------------------ */
  /* Subscriptions                                                */
  /* ------------------------------------------------------------ */

  getSnapshot(): TransportSnapshot {
    return {
      mode: this.mode,
      playing: this.playing,
      duration: this.duration,
      time: this.currentTime(),
      loop: this.loop,
      ready: this.ready,
      error: this.error,
      loading: this.loading,
    };
  }

  subscribeState(listener: (snapshot: TransportSnapshot) => void): () => void {
    this.stateListeners.add(listener);
    listener(this.getSnapshot());
    return () => this.stateListeners.delete(listener);
  }

  subscribeTime(listener: (time: number) => void): () => void {
    this.timeListeners.add(listener);
    return () => this.timeListeners.delete(listener);
  }

  private emitState(): void {
    const snapshot = this.getSnapshot();
    this.stateListeners.forEach((listener) => listener(snapshot));
  }

  private emitTime(time: number): void {
    this.timeListeners.forEach((listener) => listener(time));
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.pause();
    this.stopTick();
    this.releaseAudioGraph();
    if (this.element) {
      try {
        this.element.pause();
        this.element.removeAttribute("src");
        this.element.load();
      } catch {
        /* ignore */
      }
      this.element = null;
    }
    this.stateListeners.clear();
    this.timeListeners.clear();
    this.mode = "idle";
    this.ready = false;
  }
}

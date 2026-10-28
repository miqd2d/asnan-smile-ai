/**
 * Real microphone level for the orb, from the Web Audio API (AnalyserNode RMS).
 * It only MEASURES the stream; speech-to-text is done separately by SpeechListener.
 * One getUserMedia stream is kept for the whole call (one permission prompt), and fully released by stop().
 */
export class MicMeter {
  private stream: MediaStream | null = null;
  private ctx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private floatBuf: Float32Array<ArrayBuffer> | null = null;
  private byteBuf: Uint8Array<ArrayBuffer> | null = null;
  private smoothed = 0;

  static get supported(): boolean {
    return typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
  }

  get running(): boolean {
    return this.stream !== null;
  }

  /** True when a level can be measured (false if only the permission check succeeded). */
  get metering(): boolean {
    return this.analyser !== null;
  }

  async start(): Promise<void> {
    if (this.stream) return;
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    try {
      const AC: typeof AudioContext | undefined =
        window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AC) return;
      this.ctx = new AC();
      if (this.ctx.state === "suspended") await this.ctx.resume().catch(() => undefined);
      const source = this.ctx.createMediaStreamSource(this.stream);
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 512;
      this.analyser.smoothingTimeConstant = 0.5;
      source.connect(this.analyser);
      if (typeof this.analyser.getFloatTimeDomainData === "function") this.floatBuf = new Float32Array(this.analyser.fftSize);
      else this.byteBuf = new Uint8Array(this.analyser.fftSize);
    } catch {
      this.analyser = null; // permission is granted but metering is unavailable: the orb falls back gracefully
    }
  }

  /** 0..1, smoothed (fast attack, slower release). Call every animation frame. */
  getLevel(): number {
    if (!this.analyser) return 0;
    let sum = 0;
    if (this.floatBuf) {
      this.analyser.getFloatTimeDomainData(this.floatBuf);
      for (let i = 0; i < this.floatBuf.length; i++) sum += this.floatBuf[i] * this.floatBuf[i];
      sum /= this.floatBuf.length;
    } else if (this.byteBuf) {
      this.analyser.getByteTimeDomainData(this.byteBuf);
      for (let i = 0; i < this.byteBuf.length; i++) { const v = (this.byteBuf[i] - 128) / 128; sum += v * v; }
      sum /= this.byteBuf.length;
    }
    const target = Math.min(1, Math.sqrt(sum) * 5);               // speech RMS is roughly 0.02 - 0.2
    this.smoothed += (target - this.smoothed) * (target > this.smoothed ? 0.5 : 0.12);
    return this.smoothed;
  }

  stop(): void {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.analyser = null;
    this.floatBuf = this.byteBuf = null;
    this.smoothed = 0;
    void this.ctx?.close().catch(() => undefined);
    this.ctx = null;
  }
}

// Núcleo do TITAN Central: o orbe (respira, ouve, pensa, fala) e o quarto em holograma.
// Leve de propósito: se o notebook não aguentar (< 24 quadros/s), entra em modo leve sozinho
// (menos partículas, sem brilho borrado e 30 quadros/s).

export type CoreMode = "idle" | "listen" | "think" | "speak";
export interface HoloDevice { id: string; name: string; kind: string; icon: string; on: boolean; flashAt?: number }

const W = 840, H = 780, CX = 420, CY = 350;

export class Core {
  mode: CoreMode = "idle";
  holo = false;
  lite = false;
  devices: HoloDevice[] = [];
  onLite: (lite: boolean) => void = () => undefined;
  private ctx: CanvasRenderingContext2D;
  private canvas: HTMLCanvasElement;
  private raf = 0;
  private level = 0;
  private expand = 1;
  private holoMix = 0;
  private parts: { a: number; r: number; s: number; z: number }[] = [];
  private frames: number[] = [];
  private lastDraw = 0;
  private forcedLite: boolean | null;

  constructor(canvas: HTMLCanvasElement, forcedLite: boolean | null = null) {
    this.ctx = canvas.getContext("2d")!;
    this.canvas = canvas;
    this.forcedLite = forcedLite;
    // notebook fraco (2 núcleos ou menos, como o Pentium T4500): já começa leve
    const weak = typeof navigator !== "undefined" && (navigator.hardwareConcurrency ?? 4) <= 2;
    if (forcedLite || (forcedLite === null && weak)) this.applyLite(true);
    this.makeParts();
    this.raf = requestAnimationFrame(this.frame);
  }

  stop(): void { cancelAnimationFrame(this.raf); }

  flash(id: string): void { const d = this.devices.find((x) => x.id === id); if (d) d.flashAt = performance.now(); }

  setLite(v: boolean): void {
    if (this.lite === v) return;
    this.applyLite(v); this.makeParts(); this.onLite(v);
  }

  /** Leve = desenha em meia resolução (4x menos pixels; a tela estica) e a 30 quadros/s. */
  private applyLite(v: boolean): void {
    this.lite = v;
    const scale = v ? 0.5 : 1;
    this.canvas.width = W * scale;
    this.canvas.height = H * scale;
    this.ctx.setTransform(scale, 0, 0, scale, 0, 0);
  }

  private makeParts(): void {
    const n = this.lite ? 24 : 70;
    this.parts = Array.from({ length: n }, () => ({ a: Math.random() * 6.28, r: 160 + Math.random() * 170,
      s: (Math.random() * 0.5 + 0.2) * (Math.random() < 0.5 ? -1 : 1), z: Math.random() }));
  }

  private frame = (t: number) => {
    this.raf = requestAnimationFrame(this.frame);
    if (document.hidden) return;
    if (this.lite && t - this.lastDraw < (this.mode === "idle" && !this.holo ? 50 : 33)) return; // leve: 20–30 quadros/s
    // mede o desempenho nos primeiros segundos e de tempos em tempos
    this.frames.push(t); while (this.frames.length && t - this.frames[0] > 3000) this.frames.shift();
    if (this.forcedLite === null && !this.lite && this.frames.length > 10 && t > 4000) {
      const fps = (this.frames.length - 1) / ((t - this.frames[0]) / 1000);
      if (fps < 24) this.setLite(true);
    }
    this.lastDraw = t;
    const s = t / 1000, m = this.mode;
    const target = m === "listen" ? 0.35 + 0.65 * Math.abs(Math.sin(s * 7) * Math.sin(s * 3.1 + 1))
      : m === "speak" ? 0.25 + 0.6 * Math.abs(Math.sin(s * 9) * Math.cos(s * 2.3)) : m === "think" ? 0.3 : 0.06;
    this.level += (target - this.level) * 0.18;
    this.expand += ((m === "idle" ? 1 : 1.22) - this.expand) * 0.06;
    this.holoMix += ((this.holo ? 1 : 0) - this.holoMix) * 0.06;
    const c = this.ctx;
    c.clearRect(0, 0, W, H);
    if (this.holoMix < 0.98) this.drawOrb(s, 1 - this.holoMix);
    if (this.holoMix > 0.02) this.drawHolo(s, this.holoMix);
  };

  private drawOrb(s: number, a: number): void {
    const o = this.ctx, think = this.mode === "think";
    const [r, g, b] = think ? [255, 79, 216] : [62, 232, 255];
    const col = (al: number) => `rgba(${r},${g},${b},${al * a})`;
    const E = this.expand, br = 1 + Math.sin(s * 1.6) * 0.025, lite = this.lite;
    o.save(); o.translate(CX, CY);
    const glow = o.createRadialGradient(0, 0, 10, 0, 0, 330 * E);
    glow.addColorStop(0, col(0.32 + this.level * 0.3)); glow.addColorStop(0.35, col(0.08)); glow.addColorStop(1, col(0));
    o.fillStyle = glow; o.beginPath(); o.arc(0, 0, 330 * E, 0, 6.28); o.fill();
    for (const p of this.parts) {
      p.a += p.s * 0.004 * (think ? 4 : 1) * (lite ? 2 : 1); const rr = p.r * E;
      o.fillStyle = col(0.25 + p.z * 0.6); o.fillRect(Math.cos(p.a) * rr, Math.sin(p.a) * rr * 0.92, 2 + p.z * 2, 2 + p.z * 2);
    }
    o.lineWidth = 2;
    const rings: [number, number, number[]][] = [[150, 0.5, [40, 14]], [196, -0.3, [3, 9]], [244, 0.18, [120, 30, 10, 30]], [290, -0.1, [2, 18]]];
    rings.forEach(([rad, sp, dash], i) => {
      o.save(); o.rotate(s * sp * (think ? 4 : 1)); o.setLineDash(dash); o.strokeStyle = col(i === 2 ? 0.75 : 0.45);
      o.beginPath(); o.arc(0, 0, rad * E * br, 0, 6.28); o.stroke(); o.restore();
    });
    o.setLineDash([]);
    o.save(); o.rotate(-s * 0.4); o.strokeStyle = `rgba(255,79,216,${0.8 * a})`; o.lineWidth = 4;
    o.beginPath(); o.arc(0, 0, 244 * E, 0, 0.5); o.stroke(); o.beginPath(); o.arc(0, 0, 244 * E, 3.14, 3.4); o.stroke(); o.restore();
    if (!lite) {
      o.save(); o.rotate(s * 0.05);
      for (let i = 0; i < 72; i++) {
        const an = i / 72 * 6.28, l = i % 6 === 0 ? 14 : 6; o.strokeStyle = col(i % 6 === 0 ? 0.8 : 0.35);
        o.beginPath(); o.moveTo(Math.cos(an) * 318 * E, Math.sin(an) * 318 * E);
        o.lineTo(Math.cos(an) * (318 + l) * E, Math.sin(an) * (318 + l) * E); o.stroke();
      }
      o.restore();
    }
    o.lineWidth = 2.5; o.strokeStyle = col(0.95);
    if (!lite) { o.shadowColor = col(1); o.shadowBlur = 18; }
    o.beginPath();
    const steps = lite ? 90 : 180;
    for (let i = 0; i <= steps; i++) {
      const an = i / steps * 6.28;
      const w = this.level * (Math.sin(an * 6 + s * 8) * 22 + Math.sin(an * 11 - s * 13) * 14 + Math.sin(an * 3 + s * 5) * 10);
      const rad = (118 + w) * E * br; o.lineTo(Math.cos(an) * rad, Math.sin(an) * rad);
    }
    o.closePath(); o.stroke(); o.shadowBlur = 0;
    const core = o.createRadialGradient(0, 0, 0, 0, 0, 92 * E);
    core.addColorStop(0, `rgba(255,255,255,${0.95 * a})`); core.addColorStop(0.25, col(0.9)); core.addColorStop(0.7, col(0.25)); core.addColorStop(1, col(0));
    o.fillStyle = core; o.beginPath(); o.arc(0, 0, (78 + this.level * 26) * E * br, 0, 6.28); o.fill();
    o.fillStyle = `rgba(0,22,30,${0.85 * a})`; o.font = "700 30px ui-monospace,monospace"; o.textAlign = "center"; o.textBaseline = "middle";
    o.fillText("T", 0, 2);
    o.restore();
  }

  // Onde cada tipo de aparelho fica no quarto (aproximado; a planta real virá depois).
  private posFor(d: HoloDevice, i: number): [number, number, number] {
    if (d.kind === "light") return [0, 2.5, 0];
    if (d.kind === "ac") return [0, 2.1, -1.45];
    if (d.kind === "tv") return [-1.95, 1.3, 0.6];
    if (d.icon === "laptop") return [-1.5, 0.8, -1.0];
    const spots: [number, number, number][] = [[1.6, 0.3, 1.1], [1.7, 0.4, -1.1], [-1.7, 0.4, 1.2], [0.9, 0.3, -1.3], [-0.6, 0.3, 1.3]];
    return spots[i % spots.length];
  }

  private drawHolo(s: number, a: number): void {
    const o = this.ctx, ang = s * 0.25, tilt = 0.5, scale = 128, lite = this.lite;
    const P = ([x, y, z]: number[]): [number, number, number] => {
      const cx = x * Math.cos(ang) - z * Math.sin(ang), cz = x * Math.sin(ang) + z * Math.cos(ang);
      const yy = (y - 1.2) * Math.cos(tilt) - cz * Math.sin(tilt), zz = (y - 1.2) * Math.sin(tilt) + cz * Math.cos(tilt), f = 7 / (7 + zz);
      return [CX + cx * scale * f, CY + 40 - yy * scale * f, f];
    };
    const L = (p: number[], q: number[], al: number, w = 1.5) => {
      const A = P(p), B = P(q); o.strokeStyle = `rgba(62,232,255,${al * a})`; o.lineWidth = w;
      o.beginPath(); o.moveTo(A[0], A[1]); o.lineTo(B[0], B[1]); o.stroke();
    };
    o.save();
    if (!lite) { o.shadowColor = `rgba(62,232,255,${a})`; o.shadowBlur = 12; }
    for (let i = -2; i <= 2; i += 0.5) L([i, 0, -1.5], [i, 0, 1.5], 0.18, 1);
    for (let k = -1.5; k <= 1.5; k += 0.5) L([-2, 0, k], [2, 0, k], 0.18, 1);
    const X = 2, Y = 2.6, Z = 1.5;
    const v = [[-X, 0, -Z], [X, 0, -Z], [X, 0, Z], [-X, 0, Z], [-X, Y, -Z], [X, Y, -Z], [X, Y, Z], [-X, Y, Z]];
    const edges = [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4], [0, 4], [1, 5], [2, 6], [3, 7]];
    edges.forEach(([i, j]) => L(v[i], v[j], 0.8, 2));
    const box = (x0: number, x1: number, y1: number, z0: number, z1: number) => {
      const b = [[x0, 0, z0], [x1, 0, z0], [x1, 0, z1], [x0, 0, z1], [x0, y1, z0], [x1, y1, z0], [x1, y1, z1], [x0, y1, z1]];
      edges.forEach(([i, j]) => L(b[i], b[j], 0.55, 1.3));
    };
    box(0.2, 1.9, 0.5, -0.2, 1.4); box(-1.95, -1.0, 0.75, -1.45, -0.5);
    L([X, 0, -1.2], [X, 2.0, -1.2], 0.5); L([X, 2.0, -1.2], [X, 2.0, -0.4], 0.5); L([X, 2.0, -0.4], [X, 0, -0.4], 0.5);
    const now = performance.now();
    let other = 0;
    for (const d of this.devices) {
      const pos = this.posFor(d, d.kind === "light" || d.kind === "ac" || d.kind === "tv" || d.icon === "laptop" ? 0 : other++);
      const [x, y, f] = P(pos), fl = d.flashAt && now - d.flashAt < 1500 ? 1 - (now - d.flashAt) / 1500 : 0;
      const rr = (d.on ? 13 : 8) * f, big = d.kind === "light";
      if (d.on) {
        const gl = o.createRadialGradient(x, y, 0, x, y, (big ? 230 : 70) * f);
        gl.addColorStop(0, `rgba(${big ? "255,240,180" : "62,232,255"},${(0.45 + fl * 0.4) * a})`); gl.addColorStop(1, "rgba(0,0,0,0)");
        o.fillStyle = gl; o.beginPath(); o.arc(x, y, (big ? 230 : 70) * f, 0, 6.28); o.fill();
      }
      if (fl) { o.strokeStyle = `rgba(62,232,255,${fl * a})`; o.lineWidth = 3; o.beginPath(); o.arc(x, y, rr + (1 - fl) * 80, 0, 6.28); o.stroke(); }
      o.fillStyle = d.on ? `rgba(62,232,255,${a})` : `rgba(60,93,107,${a})`; o.beginPath(); o.arc(x, y, rr, 0, 6.28); o.fill();
      o.shadowBlur = 0; o.font = "600 17px ui-monospace,monospace"; o.textAlign = "left";
      o.fillStyle = d.on ? `rgba(223,247,255,${a})` : `rgba(127,166,182,${a * 0.8})`;
      o.fillText(`${d.name} · ${d.on ? "ON" : "OFF"}`, x + 18, y - 12);
      if (!lite) o.shadowBlur = 12;
    }
    o.restore();
  }
}

/** Gráfico de linha para os alertas (histórico com a linha do limite e a zona de perigo). */
export function drawAlertChart(cv: HTMLCanvasElement, pts: number[], limit: number, vmax: number, unit: string, warn: boolean): void {
  const c = cv.getContext("2d"); if (!c) return;
  const Wc = cv.width, Hc = cv.height, pad = 46, vmin = unit === "°C" ? 20 : 0;
  const Y = (v: number) => Hc - pad / 2 - (Math.min(vmax, v) - vmin) / (vmax - vmin) * (Hc - pad);
  const red = warn ? "255,181,71" : "255,79,106";
  c.clearRect(0, 0, Wc, Hc); c.font = "14px monospace"; c.strokeStyle = "rgba(255,255,255,.07)";
  for (let k = 0; k < 5; k++) { const y = 20 + k * (Hc - 40) / 4; c.beginPath(); c.moveTo(pad, y); c.lineTo(Wc - 10, y); c.stroke(); }
  c.fillStyle = `rgba(${red},.12)`; c.fillRect(pad, 0, Wc - pad - 10, Y(limit));
  c.setLineDash([8, 8]); c.strokeStyle = `rgb(${red})`; c.lineWidth = 2; c.beginPath(); c.moveTo(pad, Y(limit)); c.lineTo(Wc - 10, Y(limit)); c.stroke(); c.setLineDash([]);
  c.fillStyle = `rgb(${red})`; c.fillText(`LIMITE ${limit}${unit}`, pad + 10, Y(limit) - 8);
  c.fillStyle = "#7fa6b6"; c.fillText("ÚLTIMOS MINUTOS", pad, Hc - 6);
  if (pts.length < 2) return;
  const X = (i: number) => pad + i * (Wc - pad - 10) / (pts.length - 1);
  const g = c.createLinearGradient(0, 0, 0, Hc); g.addColorStop(0, `rgba(${red},.45)`); g.addColorStop(1, `rgba(${red},0)`);
  c.beginPath(); pts.forEach((v, i) => c.lineTo(X(i), Y(v))); c.lineTo(X(pts.length - 1), Hc); c.lineTo(X(0), Hc); c.fillStyle = g; c.fill();
  c.beginPath(); pts.forEach((v, i) => c.lineTo(X(i), Y(v))); c.strokeStyle = "#fff"; c.lineWidth = 2.5; c.stroke();
  c.fillStyle = "#fff"; c.beginPath(); c.arc(X(pts.length - 1), Y(pts[pts.length - 1]), 6, 0, 6.28); c.fill();
}

/** Mini-gráfico da telemetria. */
export function drawSpark(cv: HTMLCanvasElement, pts: number[]): void {
  const c = cv.getContext("2d"); if (!c) return;
  const Wc = cv.width, Hc = cv.height;
  c.clearRect(0, 0, Wc, Hc); c.strokeStyle = "#123447"; c.beginPath();
  for (let y = Hc / 4; y < Hc; y += Hc / 4) { c.moveTo(0, y); c.lineTo(Wc, y); } c.stroke();
  if (pts.length < 2) return;
  const X = (i: number) => i * Wc / (pts.length - 1), Y = (v: number) => Hc - v / 100 * (Hc - 4);
  const g = c.createLinearGradient(0, 0, 0, Hc); g.addColorStop(0, "rgba(62,232,255,.35)"); g.addColorStop(1, "rgba(62,232,255,0)");
  c.beginPath(); pts.forEach((v, i) => c.lineTo(X(i), Y(v))); c.lineTo(Wc, Hc); c.lineTo(0, Hc); c.fillStyle = g; c.fill();
  c.beginPath(); pts.forEach((v, i) => c.lineTo(X(i), Y(v))); c.strokeStyle = "#3ee8ff"; c.lineWidth = 2; c.stroke();
}

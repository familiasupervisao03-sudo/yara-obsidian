// Abertura "IA de bordo" (estilo H1): sai da dobra espacial, o painel da ponte se desenha,
// o símbolo do TITAN se forma como constelação e o console digita a iniciação com os
// dados reais (lembranças, tarefas, lembrete). ~5 s, sem pular, sem som.
// Aparece ao entrar na conta e ao abrir o TITAN já logado (uma vez por abertura).
import { useEffect, useRef } from "react";
import { brain, displayName, type HomeData } from "../brain";

const END = 4.9;
const FADE_AT = 4.3;

const clamp = (x: number, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const ease = (x: number) => 1 - Math.pow(1 - clamp(x), 3);
const prog = (t: number, a: number, d: number) => clamp((t - a) / d);
const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");

function rng(seed: number) {
  return () => { seed = (seed * 1664525 + 1013904223) % 4294967296; return seed / 4294967296; };
}
const STARS = (() => { const r = rng(3); return Array.from({ length: 140 }, () => ({ x: (r() - 0.5) * 2, y: (r() - 0.5) * 2, z: r() })); })();

interface Line { at: number; txt: string; st: string }

function linesFor(username: string, data: HomeData | null): Line[] {
  const mem = data ? `MEMÓRIA · ${data.memory_total} ${data.memory_total === 1 ? "LEMBRANÇA" : "LEMBRANÇAS"}` : "MEMÓRIA";
  return [
    { at: 0.15, txt: "INICIANDO IA DE BORDO", st: "" },
    { at: 0.8, txt: "NAVEGAÇÃO E SENSORES", st: "OK" },
    { at: 1.4, txt: mem, st: "OK" },
    { at: 2.0, txt: window.isSecureContext ? "VÍNCULO SEGURO" : "VÍNCULO LOCAL", st: "OK" },
    { at: 2.6, txt: `OPERADOR: ${username.toUpperCase().slice(0, 18)}`, st: "RECONHECIDO" },
  ];
}

function helloFor(data: HomeData | null): { title: string; sub: string } {
  const h = new Date().getHours();
  const greet = data?.greeting ?? (h >= 5 && h < 12 ? "Bom dia" : h < 18 ? "Boa tarde" : "Boa noite");
  if (!data) return { title: greet, sub: "" };
  const open = data.today.filter((t) => !t.done_at);
  const next = open.filter((t) => t.kind === "lembrete" && t.due_at && Date.parse(t.due_at) > Date.now())
    .sort((a, b) => Date.parse(a.due_at!) - Date.parse(b.due_at!))[0];
  const parts = [open.length ? `${open.length} ${open.length === 1 ? "tarefa" : "tarefas"} hoje` : "nada pendente hoje"];
  if (next) parts.push(`lembrete às ${new Date(next.due_at!).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`);
  return { title: greet, sub: parts.join(" · ") };
}

export function BootIntro({ username, onDone }: { username: string; onDone: () => void }) {
  const root = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const data = useRef<HomeData | null>(null);

  useEffect(() => {
    brain.home().then((d) => { data.current = d; }).catch(() => undefined);
  }, []);

  useEffect(() => {
    const el = root.current!;
    const cv = canvas.current!;
    const q = <T extends Element>(sel: string) => el.querySelector(sel) as T;
    const con = q<HTMLDivElement>(".bi-console");
    const ret = q<HTMLDivElement>(".bi-reticle");
    const hor = q<HTMLDivElement>(".bi-horizon");
    const path = q<SVGPathElement>(".bi-con");
    const nodes = Array.from(el.querySelectorAll<SVGCircleElement>(".bi-nodes circle"));
    const ticks = q<HTMLDivElement>(".bi-ticks");
    const brs = Array.from(el.querySelectorAll<HTMLDivElement>(".bi-br"));
    const name = q<HTMLDivElement>(".bi-name");
    const online = q<HTMLDivElement>(".bi-online");
    const hello = q<HTMLDivElement>(".bi-hello");
    const helloTitle = q<HTMLElement>(".bi-hello b");
    const helloSub = q<HTMLElement>(".bi-hello small");
    const show = (n: HTMLElement, t: number, a: number) => {
      const p = ease(prog(t, a, 0.4));
      n.style.opacity = String(p);
      n.style.transform = `translateY(${(1 - p) * 10}px)`;
    };

    let W = 0, H = 0;
    const g = cv.getContext("2d")!;
    const resize = () => {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      W = window.innerWidth; H = window.innerHeight;
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);

    let lines = linesFor(username, null);
    let helloSet = false;
    const start = performance.now();
    let raf = 0;
    let finished = false;

    const frame = (now: number) => {
      const t = Math.min((now - start) / 1000, END);
      if (data.current && t < 1.4) lines = linesFor(username, data.current); // números reais assim que chegam
      // estrelas: sai da dobra
      g.clearRect(0, 0, W, H);
      const cx = W / 2, cy = H * 0.4, k = Math.min(W, H) / 5;
      const warp = Math.max(0, 1 - ease(prog(t, 0, 1.6)));
      for (const s of STARS) {
        const z = ((s.z - t * 0.35 * (0.2 + warp * 2.5)) % 1 + 1) % 1 + 0.02;
        const x = cx + (s.x / z) * k, y = cy + (s.y / z) * k;
        if (x < -20 || x > W + 20 || y < -20 || y > H + 20) continue;
        const len = (warp * 40) / z, ang = Math.atan2(y - cy, x - cx);
        g.strokeStyle = `rgba(${(190 + 65 * (1 - z)) | 0},240,255,${clamp(1.2 - z)})`;
        g.lineWidth = clamp(1.6 - z, 0.4, 1.6);
        g.beginPath(); g.moveTo(x, y); g.lineTo(x - Math.cos(ang) * len, y - Math.sin(ang) * len); g.stroke();
        if (len < 1.5) { g.fillStyle = g.strokeStyle; g.fillRect(x, y, 1.2, 1.2); }
      }
      if (t > 1.3 && t < 1.75) {
        const f = Math.sin(prog(t, 1.3, 0.45) * Math.PI);
        const gr = g.createRadialGradient(cx, cy, 0, cx, cy, Math.max(W, H) * 0.45);
        gr.addColorStop(0, `rgba(230,252,255,${0.85 * f})`);
        gr.addColorStop(0.25, `rgba(62,232,255,${0.35 * f})`);
        gr.addColorStop(1, "rgba(0,0,0,0)");
        g.fillStyle = gr; g.fillRect(0, 0, W, H);
      }
      // painel da ponte
      for (const b of brs) { const p = ease(prog(t, 0.05, 0.6)) * 34; b.style.width = b.style.height = `${p}px`; }
      hor.style.transform = `scaleX(${ease(prog(t, 1.5, 0.6))})`;
      ret.style.opacity = String(ease(prog(t, 1.7, 0.5)) * 0.9);
      ret.style.transform = `translate(-50%,-50%) rotate(${(1 - ease(prog(t, 1.7, 1))) * -60}deg)`;
      path.style.strokeDashoffset = String(520 * (1 - ease(prog(t, 2.15, 0.9))));
      nodes.forEach((c, i) => { c.style.opacity = String(ease(prog(t, 1.95 + i * 0.07, 0.2))); });
      ticks.style.opacity = String(prog(t, 2.2, 0.4) * 0.6);
      // console digitando
      let html = "";
      lines.forEach((l, i) => {
        if (t < l.at) return;
        const s = l.txt.slice(0, Math.floor(clamp((t - l.at) * 34, 0, l.txt.length)));
        const next = lines[i + 1];
        const stShow = l.st && s.length === l.txt.length && t > l.at + l.txt.length / 34 + 0.08;
        const caret = (!next || t < next.at) && !stShow ? '<span class="bi-caret"></span>' : "";
        html += `<div><span>&gt; ${esc(s)}${caret}</span><span class="bi-st">${stShow ? l.st : ""}</span></div>`;
      });
      con.innerHTML = html;
      // nome, online e saudação
      if (!helloSet && t > 3.5) {
        const hh = helloFor(data.current);
        helloTitle.textContent = `${hh.title}, ${displayName(username)}.`;
        helloSub.textContent = hh.sub;
        helloSet = true;
      }
      show(name, t, 3.15); show(online, t, 3.4); show(hello, t, 3.7);
      // saída: revela o TITAN por baixo
      const out = prog(t, FADE_AT, END - FADE_AT);
      el.style.opacity = String(1 - out);
      if (t >= END) {
        if (!finished) { finished = true; onDone(); }
        return;
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", resize); };
  }, [username, onDone]);

  return (
    <div className="boot-intro" ref={root} role="status" aria-label="Iniciando o TITAN">
      <canvas ref={canvas} aria-hidden="true" />
      <div className="bi-br tl" /><div className="bi-br tr" /><div className="bi-br bl" /><div className="bi-br brr" />
      <div className="bi-console" aria-hidden="true" />
      <div className="bi-horizon" />
      <div className="bi-reticle" aria-hidden="true">
        <svg viewBox="0 0 210 210">
          <circle cx="105" cy="105" r="100" fill="none" stroke="#3ee8ff" strokeWidth="1" strokeDasharray="3 5" opacity=".7" />
          <path d="M105 0v22M105 188v22M0 105h22M188 105h22" stroke="#3ee8ff" strokeWidth="2" />
          <path d="M30 30l14 14M180 30l-14 14M30 180l14-14M180 180l-14-14" stroke="#1aa6ff" strokeWidth="1.5" />
        </svg>
      </div>
      <div className="bi-sig" aria-hidden="true">
        <svg viewBox="0 0 120 120">
          <path className="bi-con" d="M60 6 106 33v54L60 114 14 87V33z M36 44h48 M60 44v50" fill="none" stroke="#3ee8ff"
                strokeWidth="1.6" strokeDasharray="520" strokeDashoffset="520" />
          <g className="bi-nodes" fill="#fff">
            {[[60, 6], [106, 33], [106, 87], [60, 114], [14, 87], [14, 33], [36, 44], [84, 44], [60, 94]].map(([x, y]) => (
              <circle key={`${x}-${y}`} cx={x} cy={y} r="3" opacity="0" />
            ))}
          </g>
        </svg>
      </div>
      <div className="bi-ticks" />
      <div className="bi-name">TITAN</div>
      <div className="bi-online">IA DE BORDO · <span>ONLINE</span></div>
      <div className="bi-hello"><b /><small /></div>
    </div>
  );
}

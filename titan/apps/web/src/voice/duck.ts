// Abaixa o som do notebook (música, vídeo...) enquanto você fala com o TITAN e enquanto ele
// responde (só com o TITAN aberto no próprio notebook); no final o servidor devolve o volume de antes. Vários motivos ao mesmo tempo
// (ouvindo + falando) contam juntos; enquanto houver algum, renova a cada 10 s.
const holder = `pg-${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36)}`;
const reasons = new Set<string>();
let beat: number | null = null;
// Só faz sentido quando o TITAN está aberto NO PRÓPRIO NOTEBOOK (o som que abaixa é o dele).
let disabled = typeof location === "undefined" || !["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);

function send(on: boolean): Promise<void> {
  if (disabled) return Promise.resolve();
  return fetch("/api/v1/voice/duck", {
    method: "POST", credentials: "same-origin", keepalive: true,
    headers: { "Content-Type": "application/json", "X-Titan-Request": "1" },
    body: JSON.stringify({ on, holder }),
  }).then((r) => r.ok ? r.json() : null).then((d) => { if (d && d.available === false) disabled = true; })
    .catch(() => undefined);
}

let ready: Promise<void> = Promise.resolve();

/** Começa a abaixar. A promessa resolve quando o som já abaixou (ou em até 0,6 s): a voz do
 *  TITAN espera por ela para não ser abaixada junto. */
export function duckStart(reason: string): Promise<void> {
  if (reasons.has(reason)) return ready;
  const first = reasons.size === 0;
  reasons.add(reason);
  if (first) {
    ready = Promise.race([send(true), new Promise<void>((ok) => setTimeout(ok, 600))]);
    beat = window.setInterval(() => void send(true), 10_000);
  }
  return ready;
}

export function duckEnd(reason: string): void {
  if (!reasons.delete(reason) || reasons.size > 0) return;
  if (beat !== null) window.clearInterval(beat);
  beat = null;
  void send(false);
}

// fechou a página no meio: devolve o volume
if (typeof window !== "undefined") window.addEventListener("pagehide", () => { if (reasons.size) { reasons.clear(); send(false); } });

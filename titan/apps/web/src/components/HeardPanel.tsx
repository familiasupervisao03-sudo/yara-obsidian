// Voz → "O que eu ouvi": as últimas falas como chegaram ao notebook (texto + áudio para escutar).
// Serve para saber se o erro é o áudio (chega cortado/baixo/com eco) ou o reconhecimento.
// O áudio fica só na memória do notebook por até 30 min (nada em disco).
import { useCallback, useEffect, useState } from "react";

interface Heard {
  id: string; at: number; engine: string; text: string; final_text: string; verdict: string;
  confidence: number | null; note: string; seconds: number; level: number;
}

const ENGINE: Record<string, string> = { groq: "Groq (internet)", xai: "Grok (internet)", vosk: "Vosk (notebook, mais fraco)" };

function levelText(l: number): string {
  return l < 150 ? "muito baixo" : l < 500 ? "baixo" : l > 12000 ? "estourado" : "bom";
}

export function HeardPanel() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Heard[] | null>(null);
  const load = useCallback(() => {
    fetch("/api/v1/voice/heard", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : []))
      .then((x: Heard[]) => setItems(x))
      .catch(() => setItems([]));
  }, []);
  useEffect(() => {
    if (!open) return;
    load();
    const id = window.setInterval(load, 5000);
    return () => window.clearInterval(id);
  }, [open, load]);
  const clear = () => {
    void fetch("/api/v1/voice/heard", { method: "DELETE", credentials: "same-origin", headers: { "X-Titan-Request": "1" } })
      .then(load);
  };
  return (
    <details className="panel heard" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>O que eu ouvi (últimas falas)</summary>
      {items === null ? <p className="small muted">Carregando…</p> : items.length === 0 ? (
        <p className="small muted">Nada ainda. Fale com o TITAN e abra aqui: aparece o texto que ele entendeu e a gravação
          para você escutar.</p>
      ) : (
        <>
          <ul className="heard-list" style={{ listStyle: "none", paddingLeft: 0 }}>
            {items.map((h) => (
              <li key={h.id} style={{ marginBottom: 14 }}>
                <div><b>{h.final_text || h.text || "(ignorado: parecia ruído/silêncio)"}</b></div>
                {h.final_text && h.text && h.final_text !== h.text && (
                  <div className="small muted">antes do seu dicionário de correções: {h.text}</div>
                )}
                <div className="small muted">
                  {new Date(h.at * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })} · {ENGINE[h.engine] ?? h.engine}
                  {" "}· {h.seconds.toFixed(1)} s · volume {levelText(h.level)}
                  {h.confidence !== null ? ` · certeza ${Math.round(h.confidence * 100)}%` : ""}
                </div>
                {h.note && <div className="small warn">{h.note}</div>}
                <audio controls preload="none" src={`/api/v1/voice/heard/${h.id}/audio`} style={{ width: "100%", marginTop: 4 }} />
              </li>
            ))}
          </ul>
          <button className="small" onClick={clear}>Apagar estas gravações</button>
        </>
      )}
      <p className="small muted">A gravação fica só na memória do notebook por até 30 minutos (some ao reiniciar).</p>
    </details>
  );
}

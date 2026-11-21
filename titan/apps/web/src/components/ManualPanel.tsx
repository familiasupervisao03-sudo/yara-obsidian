// Sistema → TITAN.md: o manual de como o TITAN age com você (só a sua conta vê).
// Você edita à vontade; o TITAN só SUGERE linhas, que entram quando você toca em Guardar.
import { useEffect, useState } from "react";
import { brain, type Manual } from "../brain";
import "./ManualPanel.css";

const SOURCE: Record<string, string> = { dono: "você editou", titan: "TITAN sugeriu, você guardou", desfazer: "desfeito" };

export function ManualPanel() {
  const [m, setM] = useState<Manual | null>(null);
  const [text, setText] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const show = (x: Manual) => { setM(x); setText(x.content); };
  useEffect(() => { brain.manual().then(show).catch((e) => setMsg((e as Error).message)); }, []);

  async function run(p: Promise<Manual>, ok: string) {
    setBusy(true);
    setMsg(null);
    try { show(await p); setMsg(ok); } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  }

  if (!m) return <div className="panel"><h3 className="panel-title">TITAN.md</h3><p className="small muted">{msg ?? "Carregando…"}</p></div>;
  const changed = text !== m.content;
  return (
    <div className="panel manual-panel">
      <h3 className="panel-title">TITAN.md · como o TITAN age com você</h3>
      <p className="small muted">O TITAN lê este manual em toda conversa (chat, voz, ligação, Central e Casa).
        Escreva do seu jeito. Ele não muda as regras de segurança nem libera gastos.</p>
      {m.suggestions.length > 0 && (
        <div className="manual-sugs">
          <p className="small"><b>O TITAN quer guardar:</b></p>
          {m.suggestions.map((s) => (
            <div key={s.id} className="acard acard-manual">
              <b>+ {s.line}</b><span className="muted small">em “{s.section}”</span>
              <span className="row">
                <button className="small" disabled={busy} onClick={() => run(brain.acceptManual(s.id), "Guardado no TITAN.md.")}>Guardar</button>
                <button className="small ghost" disabled={busy} onClick={() => run(brain.dismissManual(s.id), "Ok, não guardei.")}>Agora não</button>
              </span>
            </div>
          ))}
        </div>
      )}
      <textarea className="manual-text" value={text} spellCheck={false} rows={16} maxLength={m.max_chars}
                onChange={(e) => setText(e.target.value)} aria-label="Texto do TITAN.md" />
      <div className="row">
        <button disabled={busy || !changed} onClick={() => run(brain.saveManual(text), "Salvo. O TITAN já usa na próxima resposta.")}>Salvar</button>
        <button className="ghost" disabled={busy || changed || m.history.length === 0}
                onClick={() => run(brain.undoManual(), "Voltei para a versão anterior.")}>Desfazer última mudança</button>
        <span className="small muted">{text.length}/{m.max_chars}</span>
      </div>
      {msg && <p className="small" role="status">{msg}</p>}
      {m.history.length > 0 && (
        <details>
          <summary className="small">Histórico ({m.history.length})</summary>
          <ul className="small muted" style={{ listStyle: "none", paddingLeft: 0 }}>
            {m.history.map((h) => (
              <li key={h.id}>{new Date(h.at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })} · {SOURCE[h.source] ?? h.source}
                {h.source === "titan" && h.note ? `: “${h.note}”` : ""}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

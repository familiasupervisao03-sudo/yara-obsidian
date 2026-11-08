import { useEffect, useState } from "react";
import { brain, type BrainPrefs } from "../brain";

/** Sistema → Mensagens do TITAN: quando ele pode puxar assunto e como a memória é guardada. */
export function TitanMessagesPanel() {
  const [p, setP] = useState<BrainPrefs | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  useEffect(() => { brain.prefs().then(setP).catch(() => setP(null)); }, []);
  if (!p) return null;
  const save = (next: BrainPrefs) => {
    setP(next);
    brain.savePrefs(next).then(() => { setSaved("Salvo."); window.setTimeout(() => setSaved(null), 1500); })
      .catch((e) => setSaved((e as Error).message));
  };
  const check = (k: keyof BrainPrefs, label: string, hint?: string) => (
    <label className="check">
      <input type="checkbox" checked={Boolean(p[k])} onChange={(e) => save({ ...p, [k]: e.target.checked })} />
      <span>{label}{hint && <span className="muted small"> — {hint}</span>}</span>
    </label>
  );
  const time = (k: "bom_dia" | "boa_noite", label: string) => (
    <label className="check">
      <input type="checkbox" checked={Boolean(p[k])}
             onChange={(e) => save({ ...p, [k]: e.target.checked ? (k === "bom_dia" ? "07:00" : "21:30") : "" })} />
      <span>{label}</span>
      {p[k] && <input type="time" value={p[k]} onChange={(e) => e.target.value && save({ ...p, [k]: e.target.value })} aria-label={`Horário do ${label}`} />}
    </label>
  );
  return (
    <details className="panel">
      <summary className="panel-title">Mensagens do TITAN {saved && <span className="muted small">{saved}</span>}</summary>
      <p className="muted small">Ele manda aviso no celular (ative em Avisos, abaixo). Se você não responder, ele não insiste.</p>
      {time("bom_dia", "Bom dia (resumo do dia)")}
      {time("boa_noite", "Boa noite (como foi o dia)")}
      <label className="check">
        <input type="checkbox" checked={p.papo} onChange={(e) => save({ ...p, papo: e.target.checked })} />
        <span>Papo solto, só para trocar ideia</span>
        {p.papo && (
          <select value={p.papo_max} onChange={(e) => save({ ...p, papo_max: Number(e.target.value) })} aria-label="Quantas vezes por dia">
            <option value={1}>1× por dia</option><option value={2}>2× por dia</option><option value={3}>3× por dia</option>
          </select>
        )}
      </label>
      {check("acompanhar", "Perguntar sobre assuntos em aberto", "ex.: “resolveu o microfone?”")}
      {check("socio_semana", "Conversa de sócio no domingo", "o que deu certo e o que mudar")}
      <div className="row wrap">
        <span>Silêncio das</span>
        <input type="time" value={p.silencio_inicio} onChange={(e) => e.target.value && save({ ...p, silencio_inicio: e.target.value })} aria-label="Início do silêncio" />
        <span>às</span>
        <input type="time" value={p.silencio_fim} onChange={(e) => e.target.value && save({ ...p, silencio_fim: e.target.value })} aria-label="Fim do silêncio" />
      </div>
      <p className="muted small">Lembretes que você marcou tocam na hora, mesmo no silêncio.</p>
      <h4 className="small">Memória</h4>
      {check("auto_save", "Guardar sozinho as coisas simples", "sem pedir aprovação; você revisa na aba Memória")}
    </details>
  );
}

// Você → Personalizar: cores, orbe, fundo, Início, barra de baixo, letra e o jeito do assistente.
// Cada mudança aparece na hora (no app todo) e fica salva na conta.
import { useEffect, useRef, useState } from "react";
import {
  addressOf, applyPersonal, CARD_LABEL, cachedPersonal, DEFAULT_PERSONAL, NAV_LABEL, PALETTES, palette, personalApi,
  sampleLine, type NavId, type Personal,
} from "../personal";
import { loadAppearance, saveAppearance } from "../theme/themes";
import "./Jarvis.css";

const COLOR_NAME: Record<Personal["color"], string> = {
  azul: "Azul", roxo: "Roxo", verde: "Verde", laranja: "Laranja", vermelho: "Vermelho", rosa: "Rosa", livre: "Cor livre",
};

export function PersonalizeView({ username, onBack }: { username: string; onBack: () => void }) {
  const [p, setP] = useState<Personal>(cachedPersonal);
  const [msg, setMsg] = useState<string | null>(null);
  const [leve, setLeve] = useState(() => loadAppearance().leve);
  const timer = useRef<number | null>(null);
  useEffect(() => { personalApi.get().then((x) => { setP(x); applyPersonal(x); }).catch(() => undefined); }, []);
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);

  const change = (patch: Partial<Personal>) => {
    const next = { ...p, ...patch };
    setP(next);
    // cor e fundo são do tema Vidro: se estiver em outro tema, volta para o Vidro
    if ((patch.color || patch.bg) && !(document.documentElement.dataset.theme ?? "").startsWith("vidro")) {
      saveAppearance({ ...loadAppearance(), theme: "vidro" });
    }
    applyPersonal(next);
    if (timer.current) window.clearTimeout(timer.current);
    setMsg("Salvando…");
    timer.current = window.setTimeout(() => {
      personalApi.save(next).then(() => setMsg("Salvo ✓")).catch((e) => setMsg((e as Error).message));
    }, 600);
  };
  const seg = <K extends keyof Personal>(k: K, items: [Personal[K], string][]) => (
    <div className="pz-seg" role="group">
      {items.map(([v, label]) => (
        <button key={String(v)} type="button" className={`ghost small ${p[k] === v ? "on" : ""}`}
                aria-pressed={p[k] === v} onClick={() => change({ [k]: v } as Partial<Personal>)}>{label}</button>
      ))}
    </div>
  );
  const move = (i: number, d: number) => {
    const cards = [...p.cards];
    const j = i + d;
    if (j < 0 || j >= cards.length) return;
    [cards[i], cards[j]] = [cards[j], cards[i]];
    change({ cards });
  };
  const setNav = (i: number, v: NavId) => {
    const nav = [...p.nav];
    const other = nav.indexOf(v);
    if (other >= 0) nav[other] = nav[i];  // troca de lugar em vez de repetir
    nav[i] = v;
    change({ nav });
  };

  return (
    <section className="pz" aria-labelledby="pz-title">
      <div className="row between">
        <button className="ghost small" onClick={onBack}>‹ Você</button>
        <span className="muted small" role="status">{msg}</span>
      </div>
      <h1 id="pz-title" className="home-title">Personalizar</h1>
      <p className="muted small">Mude do seu jeito: aparece na hora e fica salvo na sua conta.</p>

      <section className="card">
        <h2 className="card-title">🎨 Cor</h2>
        <div className="pz-colors">
          {(Object.keys(PALETTES) as Personal["color"][]).map((c) => {
            const [, b, d] = PALETTES[c as keyof typeof PALETTES];
            return <button key={c} type="button" title={COLOR_NAME[c]} aria-label={COLOR_NAME[c]} aria-pressed={p.color === c}
                           className={`pz-dot ${p.color === c ? "on" : ""}`} style={{ background: `linear-gradient(135deg, ${d}, ${b})` }}
                           onClick={() => change({ color: c })} />;
          })}
          <label className={`pz-dot pz-free ${p.color === "livre" ? "on" : ""}`} title="Cor livre">
            <input type="color" value={p.custom} aria-label="Cor livre" onChange={(e) => change({ color: "livre", custom: e.target.value })} />
          </label>
        </div>
        <p className="muted small">Cor: <b style={{ color: palette(p)[0] }}>{COLOR_NAME[p.color]}</b></p>
      </section>

      <section className="card">
        <h2 className="card-title">🌌 Fundo</h2>
        {seg("bg", [["brilho", "Brilho suave"], ["liso", "Liso"], ["preto", "Preto (gasta menos bateria)"]])}
      </section>

      <section className="card">
        <h2 className="card-title">🔮 Orbe</h2>
        <div className="pz-orbs">
          {([["vidro", "Vidro"], ["reator", "Reator"], ["simples", "Simples"]] as [Personal["orb"], string][]).map(([v, label]) => (
            <button key={v} type="button" className={`pz-orb ${p.orb === v ? "on" : ""}`} aria-pressed={p.orb === v}
                    onClick={() => change({ orb: v })}>
              <span className={`glass-orb pz-orb-${v}`} aria-hidden="true" />{label}
            </button>
          ))}
        </div>
        <label className="check"><input type="checkbox" checked={p.orb_anim} onChange={(e) => change({ orb_anim: e.target.checked })} />
          <span>Orbe “respirando” (animação)</span></label>
        <label className="check"><input type="checkbox" checked={leve} onChange={(e) => {
          setLeve(e.target.checked); saveAppearance({ ...loadAppearance(), leve: e.target.checked }); applyPersonal(p);
        }} /><span>Modo leve <span className="muted small">— sem vidro embaçado nem animação (só neste aparelho)</span></span></label>
      </section>

      <section className="card">
        <h2 className="card-title">🏠 Tela inicial</h2>
        <p className="muted small">Ligue, desligue e mude a ordem dos cartões do Início.</p>
        <ul className="pz-list">
          {p.cards.map((c, i) => (
            <li key={c.id}>
              <label className="check"><input type="checkbox" checked={c.on}
                onChange={(e) => change({ cards: p.cards.map((x) => x.id === c.id ? { ...x, on: e.target.checked } : x) })} />
                <span>{CARD_LABEL[c.id]}</span></label>
              <span className="pz-arrows">
                <button type="button" className="ghost small" disabled={i === 0} onClick={() => move(i, -1)} aria-label={`Subir ${CARD_LABEL[c.id]}`}>▲</button>
                <button type="button" className="ghost small" disabled={i === p.cards.length - 1} onClick={() => move(i, 1)} aria-label={`Descer ${CARD_LABEL[c.id]}`}>▼</button>
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="card">
        <h2 className="card-title">📱 Barra de baixo</h2>
        <p className="muted small">O meio é sempre a orbe (Falar). Escolha os outros 4.</p>
        <div className="pz-slots">
          {[0, 1, -1, 2, 3].map((i) => i < 0
            ? <span key="orb" className="pz-slot-orb"><span className="glass-orb" aria-hidden="true" />Falar</span>
            : (
              <select key={i} value={p.nav[i]} onChange={(e) => setNav(i, e.target.value as NavId)} aria-label={`Botão ${i + 1} da barra`}>
                {(Object.keys(NAV_LABEL) as NavId[]).map((n) => <option key={n} value={n}>{NAV_LABEL[n]}</option>)}
              </select>
            ))}
        </div>
        {!p.nav.includes("system") && <p className="warn small">Sem “Você” na barra, esta tela abre pelo Início → Atalhos ou pela Memória.</p>}
      </section>

      <section className="card">
        <h2 className="card-title">🔠 Tamanho da letra</h2>
        {seg("font", [["P", "P"], ["M", "M"], ["G", "G"], ["GG", "GG"]])}
      </section>

      <section className="card">
        <h2 className="card-title">🤖 Assistente</h2>
        <label className="pz-field">Nome do assistente
          <input value={p.name} maxLength={16} onChange={(e) => change({ name: e.target.value || "TITAN" })} />
        </label>
        <p className="small pz-label">Como ele te chama</p>
        {seg("call", [["senhor", "Senhor"], ["chefe", "Chefe"], ["nome", "Pelo nome"], ["livre", "Outro…"]])}
        {p.call === "livre" && (
          <input className="pz-call" placeholder="Ex.: capitão" value={p.call_custom} maxLength={16}
                 onChange={(e) => change({ call_custom: e.target.value })} aria-label="Como ele deve te chamar" />
        )}
        <p className="small pz-label">Jeito de falar</p>
        {seg("tone", [["formal", "Formal (mordomo)"], ["amigo", "Amigo"], ["direto", "Direto ao ponto"]])}
        <p className="muted small pz-label">Exemplo:</p>
        <div className="pz-example"><b>{p.name}:</b> {sampleLine(p, username)}</div>
        <p className="muted small">Vale também para as mensagens no celular e as respostas na conversa
          (ele vai te chamar de “{addressOf(p, username)}”). A palavra para chamar na voz continua “Titã”.</p>
      </section>

      <div className="pz-actions">
        <button className="ghost" onClick={() => {
          if (!confirm("Voltar tudo ao padrão?")) return;
          personalApi.reset().then((x) => { setP(x); applyPersonal(x); setMsg("Padrão restaurado ✓"); })
            .catch(() => { setP(DEFAULT_PERSONAL); applyPersonal(DEFAULT_PERSONAL); });
        }}>Voltar ao padrão</button>
        <button onClick={onBack}>Pronto</button>
      </div>
    </section>
  );
}

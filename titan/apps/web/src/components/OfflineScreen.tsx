// Tela "notebook fora do alcance": tenta reconectar sozinha a cada 10 s.
// As telas continuam montadas por baixo, então mensagens pendentes não se perdem.
import { useEffect, useState } from "react";
import { Icon } from "./icons";

const EVERY = 10;

export function OfflineScreen({ onRetry }: { onRetry: () => void }) {
  const [left, setLeft] = useState(EVERY);
  useEffect(() => {
    const id = window.setInterval(() => {
      setLeft((v) => {
        if (v <= 1) { onRetry(); return EVERY; }
        return v - 1;
      });
    }, 1000);
    return () => window.clearInterval(id);
  }, [onRetry]);
  return (
    <div className="offline-screen" role="alertdialog" aria-live="assertive" aria-label="Notebook fora do alcance">
      <div className="offline-box">
        <span className="offline-icon" aria-hidden="true"><Icon name="plug" size={56} /></span>
        <p className="eyebrow offline-eyebrow">Conexão perdida</p>
        <h2>Notebook fora do alcance</h2>
        <p className="muted">O TITAN mora no seu notebook. Confira se ele está <strong>ligado</strong>, com o TITAN aberto,
          e se este aparelho está na <strong>mesma Wi-Fi</strong> (ou no Tailscale, fora de casa).</p>
        <button className="big" onClick={() => { setLeft(EVERY); onRetry(); }}>Reconectar agora</button>
        <p className="offline-log">&gt; nova tentativa em {String(left).padStart(2, "0")} s…<br />
          &gt; mensagens não enviadas ficam guardadas e vão sozinhas quando ele voltar</p>
      </div>
    </div>
  );
}

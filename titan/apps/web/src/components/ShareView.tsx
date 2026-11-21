// "Compartilhar → TITAN": o que veio de outro app e o que fazer com isso.
import type { ChatIntent } from "./Shell";
import { Icon } from "./icons";

export interface Shared { title: string; text: string; url: string }

export function ShareView({ shared, webEnabled, onAction, onClose }: {
  shared: Shared;
  webEnabled: boolean;
  onAction: (intent: ChatIntent) => void;
  onClose: () => void;
}) {
  // Alguns apps mandam o link dentro do texto.
  const url = shared.url || (shared.text.match(/https?:\/\/\S+/)?.[0] ?? "");
  const text = shared.text.replace(url, "").trim();
  const subject = [shared.title, text].filter(Boolean).join(" — ").slice(0, 600);
  const ref = [subject, url].filter(Boolean).join(" ");
  let site = "";
  try { site = url ? new URL(url).hostname.replace(/^www\./, "") : ""; } catch { /* link inválido */ }
  return (
    <div className="share-overlay" role="dialog" aria-modal="true" aria-label="Recebido de outro app">
      <div className="share-box">
        <div className="row between">
          <p className="eyebrow">Recebido</p>
          <button className="ghost small" onClick={onClose}>Fechar</button>
        </div>
        <div className="share-received">
          <strong>{url ? "Você compartilhou um link" : "Você compartilhou um texto"}</strong>
          <span className="muted">{site && `${site} · `}{subject || url}</span>
        </div>
        <h2>O que o TITAN faz com isso?</h2>
        <div className="share-options">
          <button className="ghost share-opt" onClick={() => onAction({ draft: `Resuma isto para mim: ${ref}`, send: true, web: url ? true : undefined, newConversation: true })}
                  disabled={Boolean(url) && !webEnabled}>
            <Icon name="list" size={22} /> Resumir
          </button>
          <button className="ghost share-opt" onClick={() => onAction({ draft: `Explica em vídeo: ${ref}`, send: true, web: url ? true : undefined, newConversation: true })}
                  disabled={Boolean(url) && !webEnabled}>
            <Icon name="play" size={22} /> Explicar em vídeo-aula
          </button>
          <button className="ghost share-opt" onClick={() => onAction({ draft: `Sobre isto (${ref}): `, newConversation: true })}>
            <Icon name="chat" size={22} /> Perguntar sobre isso…
          </button>
          <button className="ghost share-opt" onClick={() => onAction({ draft: `pesquisa na internet sobre ${subject || url}`, send: true, web: true, newConversation: true })}
                  disabled={!webEnabled}>
            <Icon name="globe" size={22} /> Pesquisar mais sobre o assunto
          </button>
        </div>
        <p className="small muted">
          {url ? (webEnabled ? "O TITAN lê a página do link (num vídeo, só o título e a descrição — ele não assiste ao vídeo)."
            : "Para ler links, ligue a pesquisa na internet (titan enable-web).") : "O texto vai junto com o seu pedido."}
        </p>
      </div>
    </div>
  );
}

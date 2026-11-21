// Tela 4 · "Núcleo de IA em pausa": o notebook está ok, mas a IA não respondeu.
// Explica o motivo certo (orçamento, chave, fora do ar...) e lembra que a mensagem ficou salva.
import { useEffect, useState } from "react";
import type { SystemStatus } from "@titan/api-contracts";
import { api } from "../api";

const REASONS: Record<string, { title: string; what: string; fix: string; auto?: boolean }> = {
  budget: { title: "O orçamento de hoje acabou.", what: "A IA paga já gastou o limite do dia que você definiu.",
            fix: "No notebook, rode .venv/bin/titan enable-anthropic e escolha um orçamento diário maior (ele pergunta o valor). Ou espere: volta sozinho à meia-noite." },
  blocked: { title: "A IA on-line está desligada.", what: "O TITAN está no modo local (sem enviar nada para fora).",
             fix: "Para ligar a IA da Anthropic: .venv/bin/titan enable-anthropic no notebook." },
  no_model: { title: "Nenhuma IA configurada.", what: "O TITAN ainda não tem um modelo de IA ligado.",
              fix: "No notebook: .venv/bin/titan enable-anthropic (pede a chave e o orçamento)." },
  auth: { title: "A chave da IA foi recusada.", what: "A Anthropic não aceitou a chave salva no notebook (apagada, vencida ou errada).",
          fix: "Crie uma chave nova no console da Anthropic e rode .venv/bin/titan enable-anthropic no notebook." },
  limit: { title: "Limite da Anthropic atingido.", what: "A conta da Anthropic chegou ao limite de uso ou os créditos acabaram.",
           fix: "Confira os créditos no console da Anthropic. Se for só limite por minuto, tente de novo daqui a pouco.", auto: true },
  outage: { title: "A IA está fora do ar agora.", what: "O servidor da Anthropic não respondeu direito. Não é problema no seu notebook.",
            fix: "Tente de novo em 1 minuto.", auto: true },
  network: { title: "O notebook está sem internet.", what: "O TITAN abriu, mas o notebook não conseguiu falar com a IA lá fora.",
             fix: "Confira a internet do notebook (Wi-Fi ou cabo) e tente de novo.", auto: true },
  refused: { title: "A IA recusou o pedido.", what: "A Anthropic não aceitou esta mensagem (créditos ou modelo).",
             fix: "Confira os créditos no console da Anthropic." },
};

export function AiPaused({ reason, detail, onRetry }: { reason: string; detail: string; onRetry?: () => void }) {
  const info = REASONS[reason] ?? { title: "A IA não respondeu.", what: detail, fix: "Tente de novo daqui a pouco.", auto: true };
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [help, setHelp] = useState(false);
  useEffect(() => { if (reason === "budget") api.status().then(setStatus).catch(() => undefined); }, [reason]);
  const spent = status?.paid_spent_today_brl ?? 0;
  const budget = status?.paid_budget_brl ?? 0;
  return (
    <div className="ai-paused" role="alert">
      <span className="ai-paused-k">// NÚCLEO DE IA EM PAUSA</span>
      <p className="ai-paused-title">{info.title}</p>
      {reason === "budget" && budget > 0 && (
        <>
          <span className="goal-bar warn-bar" aria-hidden="true"><i style={{ width: `${Math.min(100, (spent / budget) * 100)}%` }} /></span>
          <p className="small mono muted">R$ {spent.toFixed(2)} de R$ {budget.toFixed(2)} · volta amanhã 00:00</p>
        </>
      )}
      <p className="small muted">{info.what}</p>
      <p className="small">Sua mensagem ficou salva. Lembretes, tarefas e memória continuam funcionando.</p>
      <div className="row wrap">
        {info.auto && onRetry && <button className="small" onClick={onRetry}>Tentar de novo</button>}
        <button className="ghost small warn-btn" onClick={() => setHelp((h) => !h)} aria-expanded={help}>
          {reason === "budget" ? "Como aumentar o limite" : "Como resolver"}
        </button>
      </div>
      {help && <p className="small ai-paused-fix">{info.fix}</p>}
      {help && detail && <p className="small mono muted">Detalhe técnico: {detail}</p>}
    </div>
  );
}

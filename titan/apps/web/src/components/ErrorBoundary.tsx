import { Component, type ReactNode } from "react";

/** Se alguma tela quebrar, mostra o erro (para print) em vez de uma tela preta. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error("Erro na tela do TITAN:", error);
  }

  render() {
    const e = this.state.error;
    if (!e) return this.props.children;
    return <CrashScreen message={`${e.name}: ${e.message}`} stack={e.stack ?? ""} />;
  }
}

export function CrashScreen({ message, stack }: { message: string; stack?: string }) {
  return (
    <div className="crash" role="alert">
      <p className="eyebrow">Erro na tela</p>
      <h1>Algo deu errado ao abrir o TITAN</h1>
      <p className="muted">Tire um print desta tela e mande para quem cuida do TITAN.</p>
      <pre>{message}{"\n\n"}{(stack || "").split("\n").slice(0, 6).join("\n")}{"\n\n"}{navigator.userAgent}</pre>
      <div className="row">
        <button onClick={() => window.location.reload()}>Recarregar</button>
        <button className="ghost" onClick={() => {
          try { localStorage.removeItem("titan.view"); } catch { /* ignora */ }
          window.location.href = "/";
        }}>Voltar ao Início</button>
      </div>
    </div>
  );
}

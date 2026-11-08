// O núcleo animado do TITAN (o mesmo da Central) para usar em outras telas (ex.: TITAN Casa).
import { useEffect, useRef } from "react";
import { Core, type CoreMode } from "./core";

export function CoreOrb({ mode, className, onClick, label }: {
  mode: CoreMode; className?: string; onClick?: () => void; label?: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const core = useRef<Core | null>(null);
  useEffect(() => {
    const c = new Core(ref.current!, true); // sempre leve: tela pequena e aparelhos fracos (tablet)
    core.current = c;
    return () => c.stop();
  }, []);
  useEffect(() => { if (core.current) core.current.mode = mode; }, [mode]);
  return <canvas ref={ref} width={840} height={780} className={className} onClick={onClick}
    role={onClick ? "button" : undefined} aria-label={label} />;
}

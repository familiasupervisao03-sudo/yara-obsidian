"""Voz: roda o avaliador de voz (scripts/voice_eval) como teste de regressão.

As amostras são fixas, então o resultado deve se repetir de uma rodada para outra;
mudança indica instabilidade ou regressão. Precisa do Vosk e do modelo instalados
e do Node; sem eles a rodada é pulada com o motivo.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from titan.sim.core import Context, RoundResult

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "var/models/vosk-model-small-pt-0.3"
# Limites a partir da etapa 2 (docs/voice-eval.md): piorar além disso é regressão.
LIMITS = {"false_send": 1, "stuck_noise": 0, "stuck_speech": 1, "missed": 1, "fragmented": 0}
KEYS = ("false_trigger", "false_send", "stuck_noise", "stuck_speech", "missed", "asked_repeat",
        "fragmented", "wer_first_mean")


def run(ctx: Context, model: Path = MODEL, previous: dict | None = None) -> RoundResult:
    res = RoundResult("voz", ctx.seed)
    try:
        import vosk  # noqa: F401
    except ImportError:
        res.skipped = "biblioteca vosk não instalada (sh scripts/install_voice_local.sh)"
        return res
    if not model.exists():
        res.skipped = f"modelo Vosk não encontrado em {model}"
        return res
    if not shutil.which("node"):
        res.skipped = "Node não instalado"
        return res
    sys.path.insert(0, str(ROOT / "scripts/voice_eval"))
    import run_eval

    args = argparse.Namespace(model=model, samples=ROOT / "scripts/voice_eval/samples",
                              out=Path(ctx.workdir) / f"voz-{ctx.seed}", transcribe_ms=300, vad=None,
                              label=f"simulacao-{ctx.seed}")
    rep = run_eval.run(args)
    s = rep["summary"]
    for k, limit in LIMITS.items():
        res.check(f"{k} ≤ {limit}", s[k] <= limit, f"{s[k]}")
    res.metrics.update({k: s[k] for k in KEYS})
    res.metrics.update(vosk_finish_ms_mean=round(s["vosk_finish_ms_mean"]), rss_peak_mb=round(s["rss_peak_mb"]))
    if previous:
        changed = {k: (previous[k], s[k]) for k in KEYS if k in previous and previous[k] != s[k]}
        res.check("mesmo resultado da rodada de voz anterior", not changed, str(changed))
    shutil.rmtree(args.out, ignore_errors=True)
    return res

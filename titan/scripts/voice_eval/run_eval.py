"""Avaliação reproduzível da voz do TITAN: detecção de fala, captura e transcrição.

1. simulate.ts roda a sessão de voz REAL do navegador sobre cada WAV (relógio simulado)
   e grava o áudio que seria enviado à transcrição em cada turno.
2. Este script transcreve cada turno com o Vosk REAL, pela mesma classe do servidor
   (SttSessions, pedaços de ~400 ms como o navegador envia), e calcula as métricas.

Uso (na pasta titan/):
  .venv/bin/python scripts/voice_eval/run_eval.py [--model DIR] [--label nome]
Saída: var/voice_eval/<data>-<label>/report.md e report.json (com a configuração usada).
Só usa a biblioteca padrão + vosk; nada sai do computador.
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import statistics
import subprocess
import sys
import time
import types
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

CHUNK_BYTES = 16000 * 2 * 4 // 10  # ~400 ms, como o navegador envia


# --- métricas ----------------------------------------------------------------------

def words(text: str) -> list[str]:
    t = unicodedata.normalize("NFC", text.lower())
    t = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in t)
    return t.split()


def wer(reference: str, hypothesis: str) -> float:
    """Taxa de erro de palavras: (substituições + inserções + remoções) / palavras de referência."""
    ref, hyp = words(reference), words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / len(ref)


def frame_truth(intervals: list[list[int]], frames: int) -> list[bool]:
    truth = [False] * frames
    for a, b in intervals:
        for k in range(a // 20, min(frames, b // 20 + 1)):
            truth[k] = True
    return truth


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    return v[min(len(v) - 1, int(round(0.95 * (len(v) - 1))))]


# --- execução -------------------------------------------------------------------------

def partial_timelines(engine, samples: Path, labels: list[dict]) -> dict:
    """Texto parcial do Vosk ao longo de cada arquivo (a cada ~400 ms), para a simulação
    poder aplicar a regra de frase incompleta. Aproximação: o reconhecedor ouve o
    arquivo inteiro, não só os trechos capturados (só a última palavra importa)."""
    import wave

    out = {}
    for lab in labels:
        rec = engine.recognizer()
        with wave.open(str(samples / lab["file"])) as wf:
            data = wf.readframes(wf.getnframes())
        finals, timeline = [], []
        for i in range(0, len(data), CHUNK_BYTES):
            if rec.AcceptWaveform(data[i:i + CHUNK_BYTES]):
                finals.append(json.loads(rec.Result()).get("text", ""))
                partial = ""
            else:
                partial = json.loads(rec.PartialResult()).get("partial", "")
            timeline.append([int((i + CHUNK_BYTES) / 32), " ".join([*finals, partial]).strip()])
        out[lab["file"].removesuffix(".wav")] = timeline
    return out


def cpu_info() -> dict:
    info = {"machine": platform.machine(), "python": platform.python_version()}
    try:
        text = Path("/proc/cpuinfo").read_text()
        info["model"] = next((ln.split(":", 1)[1].strip() for ln in text.splitlines()
                              if ln.startswith("model name")), "?")
        flags = next((ln.split(":", 1)[1].split() for ln in text.splitlines() if ln.startswith("flags")), [])
        info["avx"] = "avx" in flags
        info["cores"] = sum(1 for ln in text.splitlines() if ln.startswith("processor"))
    except OSError:
        pass
    return info


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, timeout=5).stdout.strip() or "?"
    except (OSError, subprocess.TimeoutExpired):
        return "?"


def run(args: argparse.Namespace) -> dict:
    from titan.config.settings import Settings
    from titan.voice.engines import SttSessions, VoskSTT

    out = args.out or ROOT / "var" / "voice_eval" / f"{datetime.now():%Y%m%d-%H%M%S}-{args.label}"
    out.mkdir(parents=True, exist_ok=True)
    settings = Settings(_env_file=None, env="test", auth_secret="x" * 40, voice_vosk_model_dir=args.model)
    engine = VoskSTT(settings)
    st = engine.status()
    if not st.available:
        raise SystemExit(f"Vosk indisponível: {st.detail}")
    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    t0 = time.perf_counter()
    engine.recognizer()  # carrega o modelo (medido)
    load_s = time.perf_counter() - t0
    labels_all = json.loads((args.samples / "labels.json").read_text())["samples"]
    (out / "partials.json").write_text(json.dumps(partial_timelines(engine, args.samples, labels_all),
                                                  ensure_ascii=False))

    cmd = ["node", "--experimental-strip-types", "--no-warnings", str(HERE / "simulate.ts"),
           str(args.samples), str(out), str(args.transcribe_ms)] + ([str(args.vad)] if args.vad else [])
    # Sessão própria: um Ctrl+C no terminal não mata o simulador no meio (o modo
    # contínuo termina a rodada antes de parar).
    subprocess.run(cmd, check=True, cwd=ROOT, start_new_session=True)
    sim = json.loads((out / "simulation.json").read_text())
    labels = {s["file"].removesuffix(".wav"): s for s in labels_all}
    sessions = SttSessions(engine, 120)
    uid = uuid.uuid4()
    cpu0 = resource.getrusage(resource.RUSAGE_SELF)

    rows, finish_ms, audio_s, proc_s = [], [], 0.0, 0.0
    tp = fp = fn = 0
    endpoint_delays = []
    for r in sim["results"]:
        lab = labels[r["name"]]
        texts, held = [], []
        parts: dict[int, list] = {}
        for t in r["turns"]:
            pcm = (out / t["pcmFile"]).read_bytes()
            sid = sessions.open(uid)
            a = time.perf_counter()
            for i in range(0, len(pcm), CHUNK_BYTES):
                sessions.feed(sid, uid, pcm[i:i + CHUNK_BYTES])
            b = time.perf_counter()
            tr = sessions.finish(sid, uid)
            if isinstance(tr, str):  # versões antigas (linha de base) devolviam só o texto
                tr = types.SimpleNamespace(text=tr, verdict="ok", confidence=None)
            c = time.perf_counter()
            finish_ms.append((c - b) * 1000)
            proc_s += c - a
            audio_s += len(pcm) / 32000
            t.update(text=tr.text, verdict=tr.verdict, confidence=tr.confidence)
            if t["sent"]:
                parts.setdefault(t.get("message", 0), []).append(tr)
        # Mesma regra da sessão: junta as partes emendadas, ignora as de ruído e não envia
        # se todas as úteis forem "mal entendidas".
        for msg in sorted(parts):
            useful = [p for p in parts[msg] if p.verdict != "noise" and p.text.strip()]
            text = " ".join(p.text.strip() for p in useful)
            if not text:
                if any(p.text.strip() for p in parts[msg]):
                    held.append("[ruído] " + " ".join(p.text for p in parts[msg]))
            elif all(p.verdict == "unclear" for p in useful):
                held.append(f"[pediu para repetir] {text}")
            else:
                texts.append(text)
        row = {"name": r["name"], "category": lab["category"], "expected": lab["expected"],
               "triggers": r["triggers"], "turns": len(r["turns"]),
               "stuck": any(t.get("stuck") for t in r["turns"]),
               "sent_texts": texts, "held_texts": held, "notes": lab["notes"]}
        if lab["category"] == "speech":
            first = texts[0] if texts else ""
            row.update(missed=not texts, wer_first=wer(lab["expected"], first),
                       wer_all=wer(lab["expected"], " ".join(texts)), fragmented=len(texts) > 1,
                       first_word_ok=bool(texts) and words(first)[:1] == words(lab["expected"])[:1])
            truth = frame_truth(lab["owner_speech_ms"], len(r["capturing"]))
            for got, real in zip(r["capturing"], truth):
                tp += got and real
                fp += got and not real
                fn += real and not got
            if len(lab["owner_speech_ms"]) == 1:
                true_end = lab["owner_speech_ms"][0][1]
                ends = [s["atMs"] for s in r["states"] if s["state"] == "transcribing" and s["atMs"] >= true_end - 200]
                if ends:
                    endpoint_delays.append(ends[0] - true_end)
        else:
            row.update(false_trigger=r["triggers"] > 0, false_send=bool(texts))
        rows.append(row)

    cpu1 = resource.getrusage(resource.RUSAGE_SELF)
    speech = [x for x in rows if x["category"] == "speech"]
    noise = [x for x in rows if x["category"] != "speech"]
    summary = {
        "noise_samples": len(noise),
        "false_trigger": sum(x["false_trigger"] for x in noise),
        "false_send": sum(x["false_send"] for x in noise),
        "stuck_noise": sum(x["stuck"] for x in noise),
        "speech_samples": len(speech),
        "missed": sum(x["missed"] and not x["held_texts"] for x in speech),
        "asked_repeat": sum(x["missed"] and bool(x["held_texts"]) for x in speech),
        "fragmented": sum(x["fragmented"] for x in speech),
        "stuck_speech": sum(x["stuck"] for x in speech),
        "first_word_ok": sum(x["first_word_ok"] for x in speech),
        "wer_first_mean": statistics.mean(x["wer_first"] for x in speech) if speech else 0.0,
        "wer_all_mean": statistics.mean(x["wer_all"] for x in speech) if speech else 0.0,
        "vad_precision": tp / (tp + fp) if tp + fp else 0.0,
        "vad_recall": tp / (tp + fn) if tp + fn else 0.0,
        "endpoint_delay_ms_mean": statistics.mean(endpoint_delays) if endpoint_delays else None,
        "vosk_load_s": load_s,
        "vosk_finish_ms_mean": statistics.mean(finish_ms) if finish_ms else 0.0,
        "vosk_finish_ms_p95": p95(finish_ms),
        "vosk_rtf": proc_s / audio_s if audio_s else 0.0,
        "rss_peak_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "rss_model_mb": (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - rss_before) / 1024,
        "cpu_s": (cpu1.ru_utime - cpu0.ru_utime) + (cpu1.ru_stime - cpu0.ru_stime),
    }
    report = {
        "label": args.label, "when": datetime.now().isoformat(timespec="seconds"),
        "config": {"commit": git_commit(), "cpu": cpu_info(), "vosk_model": str(args.model),
                   "vad": sim["vadConfig"], "pre_roll_ms": sim["preRollMs"],
                   "simulated_transcribe_ms": sim["transcribeMs"], "samples": str(args.samples),
                   "chunk_bytes": CHUNK_BYTES,
                   "limitations": "áudio cru: sem a supressão de ruído/eco/ganho do navegador; "
                                  "ruídos e vozes são sintéticos (Piper)"},
        "summary": summary, "samples": rows,
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    (out / "report.md").write_text(markdown(report))
    for f in out.glob("*.pcm"):
        f.unlink()  # áudio temporário não fica guardado
    return report | {"out": str(out)}


def markdown(rep: dict) -> str:
    s, c = rep["summary"], rep["config"]
    pct = lambda a, b: f"{a}/{b}"
    lines = [
        f"# Avaliação de voz — {rep['label']} ({rep['when']})", "",
        f"Commit `{c['commit']}` · CPU {c['cpu'].get('model')} (AVX: {c['cpu'].get('avx')}) · "
        f"modelo `{Path(c['vosk_model']).name}` · transcrição simulada {c['simulated_transcribe_ms']} ms", "",
        f"Limitações: {c['limitations']}.", "",
        "| Métrica | Valor |", "|---|---|",
        f"| Ruídos que dispararam o detector | {pct(s['false_trigger'], s['noise_samples'])} |",
        f"| Ruídos que viraram mensagem enviada | {pct(s['false_send'], s['noise_samples'])} |",
        f"| Detector preso capturando (ruído / fala) | {s['stuck_noise']} / {s['stuck_speech']} |",
        f"| Falas perdidas | {pct(s['missed'], s['speech_samples'])} |",
        f"| Falas em que pediu para repetir (não entendeu) | {pct(s['asked_repeat'], s['speech_samples'])} |",
        f"| Falas partidas em mais de uma mensagem | {pct(s['fragmented'], s['speech_samples'])} |",
        f"| Primeira palavra correta | {pct(s['first_word_ok'], s['speech_samples'])} |",
        f"| WER médio (1ª mensagem) | {s['wer_first_mean']:.1%} |",
        f"| WER médio (todas as mensagens juntas) | {s['wer_all_mean']:.1%} |",
        f"| Detector: precisão / revocação (quadros) | {s['vad_precision']:.1%} / {s['vad_recall']:.1%} |",
        f"| Atraso para perceber o fim da fala | {s['endpoint_delay_ms_mean']:.0f} ms |" if s["endpoint_delay_ms_mean"] is not None else "| Atraso para perceber o fim da fala | — |",
        f"| Vosk: carga do modelo | {s['vosk_load_s']:.2f} s |",
        f"| Vosk: fim da fala → texto (média / p95) | {s['vosk_finish_ms_mean']:.0f} / {s['vosk_finish_ms_p95']:.0f} ms |",
        f"| Vosk: tempo de processamento ÷ duração do áudio | {s['vosk_rtf']:.2f} |",
        f"| RAM: pico do processo / do modelo | {s['rss_peak_mb']:.0f} / {s['rss_model_mb']:.0f} MB |",
        f"| CPU usada na transcrição | {s['cpu_s']:.1f} s |", "",
        "| Amostra | Categoria | Disparos | Enviado | WER |", "|---|---|---|---|---|",
    ]
    for r in rep["samples"]:
        sent = " ⏐ ".join(r["sent_texts"] + r.get("held_texts", [])) or "—"
        if r["stuck"]:
            sent = "(preso) " + sent
        w = f"{r['wer_first']:.0%}" if r["category"] == "speech" else ""
        lines.append(f"| {r['name']} | {r['category']} | {r['triggers']} | {sent} | {w} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", type=Path, default=ROOT / "var/models/vosk-model-small-pt-0.3")
    ap.add_argument("--samples", type=Path, default=HERE / "samples")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--transcribe-ms", type=int, default=300)
    ap.add_argument("--vad", type=Path, help="JSON com ajustes do detector (para comparar configurações)")
    ap.add_argument("--label", default="avaliacao")
    rep = run(ap.parse_args())
    print(markdown(rep))
    print(f"Relatório: {rep['out']}/report.md")


if __name__ == "__main__":
    main()

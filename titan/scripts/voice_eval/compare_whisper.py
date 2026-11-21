"""Compara só o reconhecimento: Vosk x whisper.cpp nas falas do avaliador.

Uso (o whisper.cpp não vem com o TITAN; compile e baixe os modelos à parte):
  .venv/bin/python scripts/voice_eval/compare_whisper.py --whisper CAMINHO/whisper-cli \\
      --whisper-models PASTA_COM_ggml-*.bin [--vosk-model DIR] [--threads 2]
Para o Pentium T4500, compile no próprio notebook com -DGGML_NATIVE=ON (usa só as
instruções que a CPU tem). Nada sai do computador.
"""
from __future__ import annotations

import argparse
import json
import resource
import statistics
import subprocess
import time
import wave
from pathlib import Path

from run_eval import HERE, ROOT, wer


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--whisper", type=Path, required=True)
    ap.add_argument("--whisper-models", type=Path, required=True)
    ap.add_argument("--models", default="tiny-q5_1,base-q5_1,small-q5_1")
    ap.add_argument("--vosk-model", type=Path, default=ROOT / "var/models/vosk-model-small-pt-0.3")
    ap.add_argument("--threads", type=int, default=2)
    args = ap.parse_args()
    from vosk import KaldiRecognizer, Model, SetLogLevel

    SetLogLevel(-1)
    labels = [s for s in json.loads((HERE / "samples/labels.json").read_text())["samples"] if s["category"] == "speech"]
    wavs = {s["file"]: HERE / "samples" / s["file"] for s in labels}
    dur = {f: wave.open(str(p)).getnframes() / 16000 for f, p in wavs.items()}
    vm = Model(str(args.vosk_model))

    def vosk(path: Path) -> str:
        r = KaldiRecognizer(vm, 16000)
        with wave.open(str(path)) as wf:
            data = wf.readframes(wf.getnframes())
        out = [json.loads(r.Result())["text"] for i in range(0, len(data), 12800) if r.AcceptWaveform(data[i:i + 12800])]
        return " ".join([*out, json.loads(r.FinalResult())["text"]])

    rows: dict[str, list] = {}
    for s in labels:
        t0 = time.perf_counter()
        text = vosk(wavs[s["file"]])
        rows.setdefault("vosk", []).append((wer(s["expected"], text), time.perf_counter() - t0, text))
    peak = {}
    for m in args.models.split(","):  # do menor para o maior: o pico dos filhos é o do modelo atual
        for s in labels:
            t0 = time.perf_counter()
            p = subprocess.run([str(args.whisper), "-m", str(args.whisper_models / f"ggml-{m}.bin"),
                                "-f", str(wavs[s["file"]]), "-l", "pt", "-t", str(args.threads),
                                "-nt", "-np", "-bs", "1", "-bo", "1"], capture_output=True, text=True)
            text = " ".join(p.stdout.split())
            rows.setdefault(f"whisper-{m}", []).append((wer(s["expected"], text), time.perf_counter() - t0, text))
        peak[f"whisper-{m}"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss // 1024
    total = sum(dur.values())
    print(f"{'reconhecedor':22s} {'WER':>6s} {'tempo/áudio':>11s} {'RAM':>7s}")
    for k, v in rows.items():
        print(f"{k:22s} {statistics.mean(x[0] for x in v):6.1%} {sum(x[1] for x in v) / total:11.2f} "
              f"{str(peak.get(k, '—')) + ' MB':>7s}")
    for i, s in enumerate(labels):
        print(f"\n{s['file'][:-4]} | {s['expected']}")
        for k, v in rows.items():
            print(f"   {k:20s} {v[i][0]:5.0%}  {v[i][2]}")


if __name__ == "__main__":
    main()

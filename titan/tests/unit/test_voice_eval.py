"""Avaliador de voz (scripts/voice_eval): métricas e amostras versionadas."""

import importlib.util
import json
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / "scripts" / "voice_eval"
spec = importlib.util.spec_from_file_location("run_eval", EVAL / "run_eval.py")
run_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_eval)


def test_wer():
    assert run_eval.wer("abre a lista de tarefas", "abre a lista de tarefas") == 0
    assert run_eval.wer("abre a lista", "Abre, a lista!") == 0  # pontuação e maiúsculas
    assert run_eval.wer("abre a lista de tarefas", "a bia lista de tarefas") == pytest.approx(0.4)
    assert run_eval.wer("sim", "") == 1
    assert run_eval.wer("", "") == 0 and run_eval.wer("", "o") == 1
    assert run_eval.wer("me mostra", "então me mostra isso") == pytest.approx(1.0)  # 2 inserções


def test_frame_truth():
    t = run_eval.frame_truth([[40, 100]], 10)
    assert t == [False, False, True, True, True, True, False, False, False, False]


def test_samples_are_16k_mono_and_labeled():
    labels = json.loads((EVAL / "samples" / "labels.json").read_text())
    assert labels["rate"] == 16000 and len(labels["samples"]) >= 20
    cats = {s["category"] for s in labels["samples"]}
    assert {"noise", "speech", "background_speech"} <= cats
    for s in labels["samples"]:
        with wave.open(str(EVAL / "samples" / s["file"])) as wf:
            assert (wf.getframerate(), wf.getnchannels(), wf.getsampwidth()) == (16000, 1, 2)
        if s["category"] == "speech":
            assert s["expected"] and s["owner_speech_ms"]
        else:
            assert s["expected"] == "" and s["owner_speech_ms"] == []


@pytest.mark.skipif(shutil.which("node") is None, reason="node não instalado")
def test_simulator_runs_the_real_session(tmp_path):
    """Roda a sessão de voz real (TypeScript) sobre duas amostras."""
    samples = tmp_path / "s"
    samples.mkdir()
    labels = json.loads((EVAL / "samples" / "labels.json").read_text())
    pick = [s for s in labels["samples"] if s["file"] in ("ruido_silencio.wav", "fala_curta.wav")]
    for s in pick:
        shutil.copy(EVAL / "samples" / s["file"], samples / s["file"])
    (samples / "labels.json").write_text(json.dumps({**labels, "samples": pick}))
    subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(EVAL / "simulate.ts"),
                    str(samples), str(tmp_path / "out"), "300"], check=True, cwd=ROOT)
    sim = json.loads((tmp_path / "out" / "simulation.json").read_text())
    by = {r["name"]: r for r in sim["results"]}
    assert by["ruido_silencio"]["triggers"] == 0 and by["ruido_silencio"]["turns"] == []
    turn = by["fala_curta"]["turns"]
    assert len(turn) == 1 and turn[0]["sent"] and turn[0]["samples"] > 16000  # mais de 1 s de áudio

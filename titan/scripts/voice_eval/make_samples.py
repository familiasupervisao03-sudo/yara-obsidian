"""Gera as amostras sintéticas da avaliação de voz (uso em desenvolvimento).

Ruídos são sintetizados por código (semente fixa: o resultado é reproduzível).
A fala é gerada com vozes Piper — por isso este script roda numa máquina com
Piper e numpy; o notebook só precisa dos WAV gerados (versionados em samples/).

Uso: python scripts/voice_eval/make_samples.py --voices DIR_COM_ONNX [--out samples]
Saída: WAV 16 kHz mono 16 bits + labels.json (categoria, texto esperado e
intervalos em que o DONO está falando).
"""

from __future__ import annotations

import argparse
import io
import json
import wave
from pathlib import Path

import numpy as np

RATE = 16_000
rng = np.random.default_rng(20261024)


# --- utilidades -------------------------------------------------------------------

def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0


def at_rms(x: np.ndarray, target: float) -> np.ndarray:
    r = rms(x)
    return x * (target / r) if r > 0 else x


def lowpass(x: np.ndarray, cutoff_hz: float, taps: int = 101) -> np.ndarray:
    n = np.arange(taps) - (taps - 1) / 2
    h = np.sinc(2 * cutoff_hz / RATE * n) * np.hamming(taps)
    return np.convolve(x, h / h.sum(), mode="same")


def resample(x: np.ndarray, src: int) -> np.ndarray:
    if src == RATE:
        return x
    x = np.convolve(x, _sinc_kernel(min(RATE, src) * 0.45 / src), mode="same")
    t = np.arange(0, len(x) / src, 1 / RATE)
    return np.interp(t, np.arange(len(x)) / src, x)


def _sinc_kernel(fc: float, taps: int = 101) -> np.ndarray:
    n = np.arange(taps) - (taps - 1) / 2
    h = np.sinc(2 * fc * n) * np.hamming(taps)
    return h / h.sum()


def seconds(s: float) -> int:
    return int(s * RATE)


# --- ruídos -------------------------------------------------------------------------

def fan(dur: float, level: float) -> np.ndarray:
    """Ventilador: ruído rosado com um zumbido leve do motor."""
    white = rng.standard_normal(seconds(dur))
    pink = lowpass(np.cumsum(white) * 0.02 + white * 0.3, 1800)
    t = np.arange(len(pink)) / RATE
    hum = 0.15 * np.sin(2 * np.pi * 120 * t)
    return at_rms(pink / (np.abs(pink).max() + 1e-9) + hum, level)


def clicks(dur: float, per_second: float, level: float) -> np.ndarray:
    """Teclado: estalos curtos (3 a 8 ms) com ressonância aguda, em ritmo de digitação."""
    out = np.zeros(seconds(dur))
    t = 0.2
    while t < dur - 0.05:
        n = seconds(rng.uniform(0.003, 0.008))
        burst = rng.standard_normal(n) * np.exp(-np.linspace(0, 6, n))
        i = seconds(t)
        out[i:i + n] += burst * rng.uniform(0.6, 1.0)
        t += rng.exponential(1 / per_second) + 0.03
    return out / (np.abs(out).max() + 1e-9) * level


def thumps(dur: float, times: list[float], freq: float, length: float, level: float) -> np.ndarray:
    """Batidas, passos e porta: senoide grave que decai, com um pouco de ruído."""
    out = np.zeros(seconds(dur))
    for t0 in times:
        n = seconds(length)
        tt = np.arange(n) / RATE
        env = np.exp(-tt / (length / 4))
        s = (np.sin(2 * np.pi * freq * tt) + 0.4 * rng.standard_normal(n)) * env
        i = seconds(t0)
        out[i:i + n] += s[: len(out) - i]
    return out / (np.abs(out).max() + 1e-9) * level


def music(dur: float, level: float) -> np.ndarray:
    """Música: acordes com harmônicos e uma batida, sem voz."""
    t = np.arange(seconds(dur)) / RATE
    chords = [(220.0, 277.2, 329.6), (196.0, 246.9, 293.7), (174.6, 220.0, 261.6), (196.0, 246.9, 293.7)]
    out = np.zeros_like(t)
    for k, chord in enumerate(chords * 3):
        a, b = k * 0.75, (k + 1) * 0.75
        m = (t >= a) & (t < b)
        for f in chord:
            for h in (1, 2, 3):
                out[m] += np.sin(2 * np.pi * f * h * t[m]) / h
    beat = thumps(dur, [x * 0.375 for x in range(int(dur / 0.375))], 60, 0.12, 1.0)
    return at_rms(out + beat * 2, level)


# --- fala ----------------------------------------------------------------------------

class Voices:
    def __init__(self, folder: Path) -> None:
        from piper import PiperVoice

        self.v = {name: PiperVoice.load(str(folder / f"pt_BR-{name}.onnx"))
                  for name in ("faber-medium", "cadu-medium", "jeff-medium")}

    def say(self, text: str, who: str = "faber-medium") -> np.ndarray:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            self.v[who].synthesize_wav(text, wf)
        buf.seek(0)
        with wave.open(buf) as wf:
            src = wf.getframerate()
            x = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16) / 32768.0
        return resample(x, src)


def trim(x: np.ndarray, thr: float = 0.01) -> np.ndarray:
    idx = np.where(np.abs(x) > thr)[0]
    return x[idx[0]: idx[-1] + 1] if len(idx) else x


class Scene:
    """Cena: fundo + falas do dono em posições conhecidas (os rótulos vêm daí)."""

    def __init__(self, dur: float) -> None:
        self.x = np.zeros(seconds(dur))
        self.owner: list[tuple[int, int]] = []

    def add(self, sig: np.ndarray, at: float, owner: bool = False) -> float:
        i = seconds(at)
        n = min(len(sig), len(self.x) - i)
        self.x[i:i + n] += sig[:n]
        if owner:
            self.owner.append((int(at * 1000), int((at + n / RATE) * 1000)))
        return at + n / RATE


def save(out: Path, name: str, scene: Scene, category: str, text: str, notes: str) -> dict:
    x = np.clip(scene.x, -1, 1)
    with wave.open(str(out / f"{name}.wav"), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes((x * 32767).astype("<i2").tobytes())
    return {"file": f"{name}.wav", "category": category, "expected": text,
            "owner_speech_ms": scene.owner, "notes": notes}


SPEECH_RMS = 0.08  # fala próxima do microfone


def build(voices: Voices, out: Path) -> list[dict]:
    labels: list[dict] = []
    say = lambda text, who="faber-medium", level=SPEECH_RMS: at_rms(trim(voices.say(text, who)), level)

    # Ruídos sem fala: nenhum turno deveria ser enviado.
    for name, dur, sig, notes in [
        ("ruido_silencio", 5, fan(5, 0.002), "quarto silencioso"),
        ("ruido_ventilador", 6, fan(6, 0.02), "ventilador do notebook, constante"),
        ("ruido_ventilador_forte", 6, fan(6, 0.045), "ventilador alto"),
        ("ruido_teclado", 6, clicks(6, 7, 0.5) + fan(6, 0.003), "digitação"),
        ("ruido_batidas", 5, thumps(5, [0.8, 2.1, 3.4], 110, 0.18, 0.6) + fan(5, 0.003), "batidas na mesa"),
        ("ruido_porta", 5, thumps(5, [1.5], 70, 0.45, 0.9) + fan(5, 0.003), "porta batendo"),
        ("ruido_passos", 6, thumps(6, [0.6, 1.2, 1.8, 2.4, 3.0, 3.6, 4.2], 90, 0.12, 0.25) + fan(6, 0.003), "passos"),
        ("ruido_musica", 7, music(7, 0.05) + fan(7, 0.003), "música sem voz"),
    ]:
        s = Scene(dur)
        s.add(sig, 0)
        labels.append(save(out, name, s, "noise", "", notes))

    # Voz de outra pessoa ao fundo, sem o dono: idealmente não dispara (difícil com detector por volume).
    s = Scene(7)
    s.add(fan(7, 0.003), 0)
    s.add(say("o jogo de ontem foi muito bom, o time ganhou nos acréscimos e a torcida comemorou bastante", "cadu-medium", 0.025), 0.5)
    labels.append(save(out, "fundo_tv_conversa", s, "background_speech", "", "outra voz baixa, como TV"))

    # Fala do dono em várias condições.
    def owner(name, text, notes, bg=None, level=SPEECH_RMS, lead=0.8, extra=None, dur=None):
        sig = say(text, level=level)
        total = dur or lead + len(sig) / RATE + 2.0
        s = Scene(total)
        s.add(bg(total) if bg else fan(total, 0.002), 0)
        s.add(sig, lead, owner=True)
        if extra:
            extra(s, lead, len(sig) / RATE)
        labels.append(save(out, name, s, "speech", text, notes))

    owner("fala_curta", "abre a lista de tarefas", "frase curta, quarto silencioso")
    owner("fala_minima", "sim", "uma palavra")
    owner("fala_giria", "e aí mano beleza me explica rapidinho como funciona o backup", "gírias")
    owner("fala_longa", "eu tava pensando em fazer um bolo de cenoura pra galera no fim de semana", "frase longa e coloquial")
    owner("fala_baixa", "qual é a capital do paraná", "voz baixa (longe do microfone)", level=0.012)
    owner("fala_primeira_palavra", "titan desliga a luz da sala", "a primeira palavra não pode ser cortada", lead=0.3)
    owner("fala_com_ventilador", "liga o modo de voz e me fala a previsão do tempo para amanhã",
          "ventilador forte (SNR ~5 dB)", bg=lambda d: fan(d, 0.045))
    owner("fala_com_teclado", "anota aí que eu preciso comprar pão e café", "digitação durante a fala",
          bg=lambda d: clicks(d, 7, 0.4) + fan(d, 0.003))
    owner("fala_com_musica", "aumenta o volume da música", "música de fundo",
          bg=lambda d: music(d, 0.03) + fan(d, 0.003))
    owner("fala_com_fundo", "me mostra as tarefas de hoje", "outra pessoa conversando ao fundo (-10 dB)",
          extra=lambda s, lead, n: s.add(say("então eu falei pra ele que não dava mais tempo de chegar lá", "cadu-medium", 0.025), lead - 0.4))
    owner("fala_sobreposta", "qual é a previsão do tempo", "duas pessoas ao mesmo tempo (-4 dB)",
          extra=lambda s, lead, n: s.add(say("eu acho que vai chover o dia inteiro amanhã", "jeff-medium", 0.05), lead + 0.2))

    # Pausas: curta (natural, deve ser um turno só) e longa depois de frase incompleta.
    for name, a, gap, b, notes in [
        ("pausa_curta", "pesquisa pra mim", 0.9, "quanto custa um notebook usado", "pausa natural de 0,9 s"),
        ("pausa_longa", "me lembra amanhã de ligar pro dentista e", 1.8,
         "depois de pagar a conta de luz", "frase incompleta, pausa de 1,8 s: deve continuar sendo ouvida"),
    ]:
        sa, sb = say(a), say(b)
        total = 0.8 + len(sa) / RATE + gap + len(sb) / RATE + 2.0
        s = Scene(total)
        s.add(fan(total, 0.002), 0)
        end_a = s.add(sa, 0.8, owner=True)
        s.add(sb, end_a + gap, owner=True)
        labels.append(save(out, name, s, "speech", f"{a} {b}", notes))
    return labels


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voices", required=True, type=Path, help="pasta com pt_BR-*.onnx do Piper")
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "samples")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    labels = build(Voices(args.voices), args.out)
    (args.out / "labels.json").write_text(json.dumps(
        {"rate": RATE, "generator": "make_samples.py", "seed": 20261024, "samples": labels},
        ensure_ascii=False, indent=1))
    print(f"{len(labels)} amostras em {args.out}")


if __name__ == "__main__":
    main()

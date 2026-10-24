"""Viabilidade da verificação do dono com o modelo de locutor do Vosk (x-vector).

Locutores SINTÉTICOS (vozes Piper): faber = "dono"; cadu, jeff, edresson = outras
pessoas. Cadastro: 3 frases do dono. Teste: frases diferentes, em condições variadas.
Aviso: vozes sintéticas são muito mais regulares que voz humana — resultado otimista.

Uso (desenvolvimento; precisa de piper, numpy e vosk):
  python scripts/voice_eval/speaker_eval.py PASTA_VOZES_PIPER PASTA_vosk-model-spk-0.4 PASTA_MODELO_VOSK
"""
import io, json, math, sys, time, wave
import numpy as np
from pathlib import Path
from piper import PiperVoice, SynthesisConfig
from vosk import Model, KaldiRecognizer, SpkModel, SetLogLevel

SetLogLevel(-1)
V = Path(sys.argv[1]); SPK = sys.argv[2]; ASR = sys.argv[3]
rng = np.random.default_rng(7)
model, spk = Model(ASR), SpkModel(SPK)
voices = {n: PiperVoice.load(str(V / f"pt_BR-{n}.onnx")) for n in ("faber-medium", "cadu-medium", "jeff-medium", "edresson-low")}

def synth(who, text, speed=1.0):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        voices[who].synthesize_wav(text, wf, syn_config=SynthesisConfig(length_scale=speed))
    buf.seek(0)
    with wave.open(buf) as wf:
        src = wf.getframerate(); x = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16) / 32768
    t = np.arange(0, len(x) / src, 1 / 16000)
    return np.interp(t, np.arange(len(x)) / src, x)

def embed(x):
    rec = KaldiRecognizer(model, 16000, spk)
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()
    for i in range(0, len(pcm), 12800): rec.AcceptWaveform(pcm[i:i + 12800])
    r = json.loads(rec.FinalResult())
    return np.array(r["spk"]) if "spk" in r else None

def cos(a, b): return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

enroll = ["olá titan, esta é a minha voz", "hoje eu quero organizar as minhas tarefas", "pode me lembrar de beber água mais tarde"]
tests = ["abre a lista de tarefas", "qual é a previsão do tempo para amanhã", "me explica como funciona o backup",
         "liga o modo de voz", "anota que eu preciso comprar café", "pesquisa quanto custa um notebook usado",
         "desliga a luz da sala", "eu tava pensando em fazer um bolo", "me mostra as mensagens de hoje", "sim"]
t0 = time.perf_counter()
ref = np.mean([embed(synth("faber-medium", t)) for t in enroll], axis=0)
conds = {"normal": lambda x: x, "rápido": None, "baixo": lambda x: x * 0.15,
         "ventilador": lambda x: x + rng.standard_normal(len(x)) * 0.02}
owner, others = [], []
for t in tests:
    for c, f in conds.items():
        x = synth("faber-medium", t, 0.8) if c == "rápido" else f(synth("faber-medium", t))
        e = embed(x)
        if e is not None: owner.append((cos(ref, e), c, t))
    for who in ("cadu-medium", "jeff-medium", "edresson-low"):
        e = embed(synth(who, t))
        if e is not None: others.append((cos(ref, e), who, t))
# mistura: dono com outra pessoa ao fundo (-8 dB)
mixed = []
for t in tests[:6]:
    a, b = synth("faber-medium", t), synth("cadu-medium", "então eu falei pra ele que não dava tempo") * 0.4
    n = max(len(a), len(b)); x = np.zeros(n); x[:len(a)] += a; x[:len(b)] += b
    e = embed(x); mixed.append(cos(ref, e))
dt = time.perf_counter() - t0
o = np.array([s for s, *_ in owner]); x = np.array([s for s, *_ in others])
best = None
for thr in np.linspace(-0.2, 1, 241):
    frr, far = float(np.mean(o < thr)), float(np.mean(x >= thr))
    if best is None or abs(frr - far) < abs(best[1] - best[2]): best = (thr, frr, far)
print(f"dono: {len(o)} frases, similaridade média {o.mean():.2f} (mín {o.min():.2f})")
for c in conds: print(f"   {c:10s} média {np.mean([s for s, cc, _ in owner if cc == c]):.2f}")
print(f"outros: {len(x)} frases, média {x.mean():.2f} (máx {x.max():.2f})")
for w in ("cadu-medium", "jeff-medium", "edresson-low"): print(f"   {w:12s} média {np.mean([s for s, ww, _ in others if ww == w]):.2f}")
print(f"dono + outra voz ao fundo: média {np.mean(mixed):.2f}")
print(f"limiar de erro igual (EER): {best[0]:.2f} → recusa o dono {best[1]:.1%}, aceita outro {best[2]:.1%}")
for thr in (0.3, 0.4, 0.5):
    print(f"limiar {thr}: recusa o dono {np.mean(o < thr):.1%} | aceita outra pessoa {np.mean(x >= thr):.1%} | mistura aceita {np.mean(np.array(mixed) >= thr):.0%}")
print(f"tempo total {dt:.1f} s para {len(o) + len(x) + len(mixed) + 3} trechos")

"""Clima pelo Open-Meteo (grátis, sem chave): cartão no Início, aviso de chuva e respostas na conversa.

Nada é inventado: todo número vem da resposta do Open-Meteo, que é citado como fonte. Previsão
é previsão: para mais de 3 dias o TITAN avisa que pode mudar.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from urllib.parse import urlencode

SOURCE = "Open-Meteo"
SOURCE_URL = "https://open-meteo.com/"
STALE = timedelta(minutes=30)
RAIN_PROB = 60          # % a partir de quando vale avisar
RAIN_AHEAD = timedelta(minutes=90)

# Códigos WMO usados pelo Open-Meteo → texto e emoji.
CODES: dict[int, tuple[str, str]] = {
    0: ("Céu limpo", "☀️"), 1: ("Quase limpo", "🌤️"), 2: ("Sol com nuvens", "⛅"), 3: ("Nublado", "☁️"),
    45: ("Neblina", "🌫️"), 48: ("Neblina", "🌫️"),
    51: ("Garoa fraca", "🌦️"), 53: ("Garoa", "🌦️"), 55: ("Garoa forte", "🌧️"),
    56: ("Garoa gelada", "🌧️"), 57: ("Garoa gelada", "🌧️"),
    61: ("Chuva fraca", "🌦️"), 63: ("Chuva", "🌧️"), 65: ("Chuva forte", "🌧️"),
    66: ("Chuva gelada", "🌧️"), 67: ("Chuva gelada", "🌧️"),
    71: ("Neve fraca", "🌨️"), 73: ("Neve", "🌨️"), 75: ("Neve forte", "🌨️"), 77: ("Neve", "🌨️"),
    80: ("Pancadas de chuva", "🌦️"), 81: ("Pancadas de chuva", "🌧️"), 82: ("Pancadas fortes", "⛈️"),
    85: ("Neve", "🌨️"), 86: ("Neve", "🌨️"),
    95: ("Trovoada", "⛈️"), 96: ("Trovoada com granizo", "⛈️"), 99: ("Trovoada com granizo", "⛈️"),
}
WEEKDAYS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")


class WeatherError(Exception):
    pass


def code_text(code: Any) -> tuple[str, str]:
    try:
        return CODES.get(int(code), ("Tempo indefinido", "🌡️"))
    except (TypeError, ValueError):
        return ("Tempo indefinido", "🌡️")


def geocode_url(name: str) -> str:
    return "https://geocoding-api.open-meteo.com/v1/search?" + urlencode(
        {"name": name[:80], "count": 6, "language": "pt", "format": "json"})


def forecast_url(lat: float, lon: float) -> str:
    return "https://api.open-meteo.com/v1/forecast?" + urlencode({
        "latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "timezone": "auto", "forecast_days": 7,
        "current": "temperature_2m,weather_code",
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
    })


def geocode(fetch: Callable[[str], str], name: str) -> list[dict]:
    """Cidades com esse nome (o dono escolhe a certa). Coordenadas vêm do Open-Meteo."""
    name = " ".join(name.split())
    if len(name) < 2:
        return []
    try:
        data = json.loads(fetch(geocode_url(name)))
    except Exception as exc:
        raise WeatherError(f"Não consegui procurar a cidade agora ({str(exc)[:80]}).") from exc
    out = []
    for r in (data.get("results") or [])[:6]:
        try:
            out.append({"name": str(r["name"])[:80], "admin1": str(r.get("admin1") or "")[:80],
                        "country": str(r.get("country") or "")[:60],
                        "lat": round(float(r["latitude"]), 4), "lon": round(float(r["longitude"]), 4)})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def fetch_forecast(fetch: Callable[[str], str], place: dict) -> dict:
    try:
        data = json.loads(fetch(forecast_url(float(place["lat"]), float(place["lon"]))))
    except Exception as exc:
        raise WeatherError(f"Previsão indisponível agora ({str(exc)[:80]}).") from exc
    if not isinstance(data, dict) or "hourly" not in data or "daily" not in data:
        raise WeatherError("O Open-Meteo respondeu sem previsão.")
    return data


# --- leitura da resposta ---------------------------------------------------------------------

def _tz(data: dict) -> timezone:
    return timezone(timedelta(seconds=int(data.get("utc_offset_seconds") or 0)))


def _hours(data: dict) -> list[tuple[datetime, Optional[int], Optional[float], Any]]:
    h = data.get("hourly") or {}
    tz = _tz(data)
    out = []
    times = h.get("time") or []
    probs = h.get("precipitation_probability") or []
    temps = h.get("temperature_2m") or []
    codes = h.get("weather_code") or []
    for i, t in enumerate(times):
        try:
            when = datetime.fromisoformat(t).replace(tzinfo=tz)
        except (TypeError, ValueError):
            continue
        p = probs[i] if i < len(probs) else None
        out.append((when, int(p) if p is not None else None, temps[i] if i < len(temps) else None,
                    codes[i] if i < len(codes) else None))
    return out


def _days(data: dict) -> list[dict]:
    d = data.get("daily") or {}
    out = []
    for i, t in enumerate(d.get("time") or []):
        try:
            day = datetime.fromisoformat(t).date()
        except (TypeError, ValueError):
            continue

        def pick(key: str):
            v = d.get(key) or []
            return v[i] if i < len(v) else None
        text, emoji = code_text(pick("weather_code"))
        out.append({"date": day.isoformat(), "weekday": WEEKDAYS[day.weekday()], "text": text, "emoji": emoji,
                    "min": pick("temperature_2m_min"), "max": pick("temperature_2m_max"),
                    "rain": pick("precipitation_probability_max")})
    return out


def summary(data: dict, now: datetime, place: dict, fetched_at: Optional[str]) -> dict:
    """Para o cartão do Início: agora, chance de chuva nas próximas horas e os 7 dias."""
    tz = _tz(data)
    local = now.astimezone(tz)
    cur = data.get("current") or {}
    text, emoji = code_text(cur.get("weather_code"))
    hours = []
    for when, prob, temp, _code in _hours(data):
        if when >= local.replace(minute=0, second=0, microsecond=0) and len(hours) < 5 and when.hour % 3 == 0:
            hours.append({"time": when.strftime("%Hh"), "rain": prob, "temp": temp})
    days = _days(data)
    tip = ""
    soon = rain_soon(data, now)
    today = days[0] if days else None
    later = [h for h in hours if (h["rain"] or 0) >= RAIN_PROB]
    if soon:
        tip = f"🌧️ Chuva por volta das {soon[0].strftime('%Hh%M')} ({soon[1]}% de chance)."
    elif later:
        tip = f"☂️ Leve guarda-chuva: {later[0]['rain']}% de chance de chuva às {later[0]['time']}."
    elif today and (today["rain"] or 0) < 20:
        tip = "Sem chuva prevista para hoje."
    return {"place": place, "source": SOURCE, "source_url": SOURCE_URL, "updated_at": fetched_at,
            "now": {"temp": cur.get("temperature_2m"), "text": text, "emoji": emoji},
            "today": today, "hours": hours, "days": days, "tip": tip}


def rain_soon(data: dict, now: datetime) -> Optional[tuple[datetime, int]]:
    """Primeira hora com chuva provável (≥ 60%) na próxima 1h30. None se não tem."""
    for when, prob, _t, _c in _hours(data):
        if now < when <= now + RAIN_AHEAD and prob is not None and prob >= RAIN_PROB:
            return when, prob
    return None


def is_stale(fetched_at: Optional[str], now: datetime) -> bool:
    if not fetched_at:
        return True
    try:
        return now - datetime.fromisoformat(fetched_at) >= STALE
    except ValueError:
        return True


# --- conversa ------------------------------------------------------------------------------

_ASK = re.compile(r"\b(chuva|chover|chove|choveu|tempo|clima|temperatura|calor|frio|previsao|guarda chuva|"
                  r"guarda-chuva|sol|nublado|graus|esquentar|esfriar)\b")


def _plain(s: str) -> str:
    t = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def context_block(data: Optional[dict], place: Optional[dict], text: str, now: datetime,
                  fetched_at: Optional[str]) -> str:
    """Previsão real para a IA responder "vai chover amanhã?". Vazio se a pergunta não é de clima."""
    if not _ASK.search(_plain(text)):
        return ""
    if not place:
        return ("Clima: o dono ainda não escolheu a cidade. Se ele perguntar do tempo, diga que não tem a "
                "previsão e que ele escolhe a cidade em Sistema → Clima e chegada. NUNCA invente previsão.")
    if not data:
        return (f"Clima: a previsão de {place.get('name')} ainda não chegou (sem internet ou Open-Meteo fora). "
                "Diga isso ao dono. NUNCA invente previsão.")
    s = summary(data, now, place, fetched_at)
    lines = [f"Previsão do tempo para {place.get('name')} (fonte: Open-Meteo, atualizada em {fetched_at or '?'}; "
             "são DADOS):",
             f"- Agora: {s['now']['temp']}°, {s['now']['text']}."]
    for d in s["days"]:
        lines.append(f"- {d['weekday']} {d['date'][8:10]}/{d['date'][5:7]}: {d['text']}, mín {d['min']}°, "
                     f"máx {d['max']}°, chance de chuva {d['rain']}%.")
    tz = _tz(data)
    local = now.astimezone(tz)
    nxt = [f"{w.strftime('%Hh')} {p}%" for w, p, _t, _c in _hours(data)
           if local <= w <= local + timedelta(hours=12) and p is not None]
    if nxt:
        lines.append("- Chance de chuva nas próximas horas: " + ", ".join(nxt) + ".")
    lines.append("Responda só com esses números, citando o Open-Meteo. Para mais de 3 dias, avise que a "
                 "previsão pode mudar. NUNCA invente previsão que não está aqui.")
    return "\n".join(lines)

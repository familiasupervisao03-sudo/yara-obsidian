"""Clima para o TITAN Central (Open-Meteo: grátis, sem chave, sem cadastro).

Só é consultado se você configurar a cidade (titan central-clima "Cidade") e o TITAN não
estiver em modo só-local. O que sai do notebook: as coordenadas da cidade, nada mais.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
CACHE_S = 20 * 60

# Códigos WMO → texto e ícone simples
_WMO = {0: ("Céu limpo", "sol"), 1: ("Quase limpo", "sol"), 2: ("Parcialmente nublado", "nuvem-sol"),
        3: ("Nublado", "nuvem"), 45: ("Neblina", "nuvem"), 48: ("Neblina", "nuvem"),
        51: ("Garoa fraca", "chuva"), 53: ("Garoa", "chuva"), 55: ("Garoa forte", "chuva"),
        61: ("Chuva fraca", "chuva"), 63: ("Chuva", "chuva"), 65: ("Chuva forte", "chuva"),
        80: ("Pancadas de chuva", "chuva"), 81: ("Pancadas de chuva", "chuva"), 82: ("Temporal", "tempestade"),
        95: ("Trovoadas", "tempestade"), 96: ("Trovoadas com granizo", "tempestade"),
        99: ("Trovoadas com granizo", "tempestade")}

_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()


class WeatherError(Exception):
    pass


def describe(code: int) -> tuple[str, str]:
    return _WMO.get(int(code), ("Tempo instável", "nuvem"))


def parse(data: dict, city: str) -> dict:
    cur = data.get("current") or {}
    daily = data.get("daily") or {}
    text, icon = describe(cur.get("weather_code", 3))

    def first(key):
        v = daily.get(key) or []
        return v[0] if v else None

    return {"city": city, "temp": round(cur.get("temperature_2m")) if cur.get("temperature_2m") is not None else None,
            "humidity": cur.get("relative_humidity_2m"), "text": text, "icon": icon,
            "max": first("temperature_2m_max"), "min": first("temperature_2m_min"),
            "rain_chance": first("precipitation_probability_max")}


def current(lat: float, lon: float, city: str, client=None) -> dict:
    """Clima agora + máxima/mínima/chance de chuva de hoje. Guarda 20 min em memória."""
    key = (round(lat, 3), round(lon, 3))
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_S:
            return hit[1]
    params = {"latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 1,
              "current": "temperature_2m,relative_humidity_2m,weather_code",
              "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max"}
    try:
        if client is None:
            import httpx
            with httpx.Client(timeout=8) as c:
                r = c.get(FORECAST_URL, params=params)
        else:
            r = client.get(FORECAST_URL, params=params)
        r.raise_for_status()
        out = parse(r.json(), city)
    except Exception as exc:  # rede fora, serviço fora: a Central só esconde o clima
        raise WeatherError(type(exc).__name__) from exc
    with _lock:
        _cache[key] = (time.time(), out)
    return out


def geocode(name: str, client=None) -> Optional[dict]:
    """Nome da cidade → {name, lat, lon, admin, country} (o primeiro resultado no Brasil, se houver)."""
    params = {"name": name, "count": 5, "language": "pt", "format": "json"}
    if client is None:
        import httpx
        with httpx.Client(timeout=10) as c:
            r = c.get(GEOCODE_URL, params=params)
    else:
        r = client.get(GEOCODE_URL, params=params)
    r.raise_for_status()
    res = r.json().get("results") or []
    if not res:
        return None
    best = next((x for x in res if x.get("country_code") == "BR"), res[0])
    return {"name": best.get("name", name), "lat": best["latitude"], "lon": best["longitude"],
            "admin": best.get("admin1", ""), "country": best.get("country", "")}

"""Conectores de aparelhos do TITAN Casa.

* ``DemoProvider``: aparelhos de demonstração (nada sai do notebook). Serve para usar
  o app antes de ligar a Tuya, e nos testes.
* ``TuyaProvider``: a sua conta Tuya/Smart Life pela API oficial da nuvem Tuya
  (projeto de desenvolvedor: access id + secret, assinatura HMAC-SHA256).

Todo provedor fala o mesmo "idioma": lista aparelhos (``RemoteDevice``) e executa
uma ação normalizada (``on``, ``off``, ``bright``, ``white``, ``ac``, ``key``),
devolvendo o estado novo normalizado:
``{"on": bool, "bright": 1-100, "white": quente|neutro|frio, "watts": float,
   "ac_temp": 16-30, "ac_mode": frio|ventilar|secar|auto|quente, "ac_fan": 0-3}``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlencode

log = logging.getLogger("titan.casa")


class ProviderError(Exception):
    """Falha ao falar com o provedor (sem internet, chave errada, aparelho offline...)."""


@dataclass
class RemoteDevice:
    provider_id: str
    name: str
    category: str
    kind: str                      # plug | light | tv | ac | fan | other
    online: bool = True
    state: dict = field(default_factory=dict)
    parent_id: Optional[str] = None  # controles IR: id do aparelhinho infravermelho
    meta: dict = field(default_factory=dict)


# --- categorias Tuya → tipo do TITAN ------------------------------------------------

PLUG_CATS = {"cz", "pc", "kg", "tdq", "dlq", "ckmkzq"}
LIGHT_CATS = {"dj", "dd", "fwd", "xdd", "dc", "tgq", "tgkg"}
FAN_CATS = {"fs", "fsd"}
IR_HUB_CATS = {"wnykq", "hwktwkq", "qt"}
IR_TV_CATEGORY_IDS = {2, 3, 4}       # TV, caixa de TV, IPTV (catálogo IR da Tuya)
IR_AC_CATEGORY_IDS = {5}
WHITE = {"quente": 0, "neutro": 500, "frio": 1000}
AC_MODE = {"frio": 0, "quente": 1, "auto": 2, "ventilar": 3, "secar": 4}
TV_KEYS = {"power": "Power", "vol_up": "Volume+", "vol_down": "Volume-", "ch_up": "Channel+",
           "ch_down": "Channel-", "mute": "Mute", "ok": "OK", "up": "Up", "down": "Down",
           "left": "Left", "right": "Right", "back": "Back", "home": "Home", "input": "Input"}


def kind_for(category: str) -> str:
    if category in PLUG_CATS:
        return "plug"
    if category in LIGHT_CATS:
        return "light"
    if category in FAN_CATS:
        return "fan"
    return "other"


def normalize_status(items: list[dict]) -> tuple[dict, dict]:
    """Status Tuya (lista de {code, value}) → (estado normalizado, meta com os códigos)."""
    st, meta = {}, {}
    by = {i.get("code"): i.get("value") for i in items if isinstance(i, dict)}
    for code in ("switch_1", "switch", "switch_led", "switch_on"):
        if code in by:
            st["on"] = bool(by[code])
            meta["switch_code"] = code
            break
    if "bright_value_v2" in by or "bright_value" in by:
        code = "bright_value_v2" if "bright_value_v2" in by else "bright_value"
        top = 1000 if code.endswith("v2") else 255
        try:
            st["bright"] = max(1, min(100, round(int(by[code]) * 100 / top)))
            meta["bright_code"], meta["bright_top"] = code, top
        except (TypeError, ValueError):
            pass
    if "temp_value_v2" in by or "temp_value" in by:
        code = "temp_value_v2" if "temp_value_v2" in by else "temp_value"
        top = 1000 if code.endswith("v2") else 255
        try:
            v = int(by[code]) / top
            st["white"] = "quente" if v < 0.34 else "neutro" if v < 0.67 else "frio"
            meta["white_code"], meta["white_top"] = code, top
        except (TypeError, ValueError):
            pass
    if "cur_power" in by:
        try:
            st["watts"] = round(float(by["cur_power"]) / 10, 1)
        except (TypeError, ValueError):
            pass
    return st, meta


# --- demonstração ----------------------------------------------------------------------

DEMO_DEVICES = [
    RemoteDevice("demo-luz", "Smart Bulb", "dj", "light", state={"on": True, "bright": 70, "white": "quente"}),
    RemoteDevice("demo-plug-1", "Smart Plug 1", "cz", "plug", state={"on": True, "watts": 38.0}),
    RemoteDevice("demo-plug-2", "Smart Plug 2", "cz", "plug", state={"on": True, "watts": 45.0}),
    RemoteDevice("demo-ir-tv", "IR Remote · TV", "infrared_tv", "tv", parent_id="demo-ir", state={"on": False}),
    RemoteDevice("demo-ir-ac", "IR Remote · AC", "infrared_ac", "ac", parent_id="demo-ir",
                 state={"on": False, "ac_temp": 24, "ac_mode": "frio", "ac_fan": 2}),
]


class DemoProvider:
    """Aparelhos de demonstração: tudo acontece no banco do notebook."""

    name = "demo"
    cloud = False

    def list_devices(self, provider_uid: Optional[str]) -> list[RemoteDevice]:
        return [RemoteDevice(d.provider_id, d.name, d.category, d.kind, d.online, dict(d.state), d.parent_id)
                for d in DEMO_DEVICES]

    def act(self, device: Any, action: dict) -> dict:
        return apply_locally(device.kind, dict(device.state or {}), action)


def apply_locally(kind: str, state: dict, action: dict) -> dict:
    """Estado depois da ação (usado pela demonstração e pelos aparelhos IR, que não informam estado)."""
    a = action.get("do")
    if a == "on":
        state["on"] = True
    elif a == "off":
        state["on"] = False
    elif a == "bright":
        state["on"], state["bright"] = True, max(1, min(100, int(action["value"])))
    elif a == "white":
        state["on"], state["white"] = True, action["value"]
    elif a == "ac":
        state["on"] = action.get("on", True)
        for k in ("ac_temp", "ac_mode", "ac_fan"):
            if k in action:
                state[k] = action[k]
    elif a == "key":
        if action["value"] == "power":
            state["on"] = not state.get("on", False)
        elif action["value"] in ("vol_up", "vol_down"):
            state["vol"] = max(0, int(state.get("vol", 10)) + (1 if action["value"] == "vol_up" else -1))
    return state


# --- Tuya (nuvem oficial) --------------------------------------------------------------

ENDPOINTS = {
    "us": "https://openapi.tuyaus.com", "eu": "https://openapi.tuyaeu.com", "cn": "https://openapi.tuyacn.com",
    "in": "https://openapi.tuyain.com", "ueaz": "https://openapi-ueaz.tuyaus.com", "weaz": "https://openapi-weaz.tuyaeu.com",
}


class TuyaProvider:
    """API oficial da nuvem Tuya. As credenciais do projeto ficam no .env do notebook."""

    name = "tuya"
    cloud = True
    TIMEOUT = 10

    def __init__(self, access_id: str, access_secret: str, region: str = "us", http: Any = None) -> None:
        self.access_id = access_id
        self.secret = access_secret.encode()
        self.base = ENDPOINTS[region]
        self._http = http  # injeção para testes
        self._token: Optional[str] = None
        self._token_exp = 0.0
        self._lock = threading.Lock()

    # assinatura (modelo "novo" da Tuya, HMAC-SHA256)
    def _sign(self, method: str, path: str, body: str, t: str, nonce: str, token: str = "") -> str:
        content_sha = hashlib.sha256(body.encode()).hexdigest()
        string_to_sign = "\n".join([method.upper(), content_sha, "", path])
        msg = self.access_id + token + t + nonce + string_to_sign
        return hmac.new(self.secret, msg.encode(), hashlib.sha256).hexdigest().upper()

    def _send(self, method: str, path: str, query: Optional[dict] = None, body: Any = None, auth: bool = True) -> Any:
        if query:
            path = f"{path}?{urlencode(sorted(query.items()))}"
        raw = json.dumps(body, separators=(",", ":")) if body is not None else ""
        token = self._get_token() if auth else ""
        t, nonce = str(int(time.time() * 1000)), uuid.uuid4().hex
        headers = {"client_id": self.access_id, "t": t, "nonce": nonce, "sign_method": "HMAC-SHA256",
                   "sign": self._sign(method, path, raw, t, nonce, token), "Content-Type": "application/json"}
        if token:
            headers["access_token"] = token
        try:
            if self._http is not None:
                data = self._http(method, self.base + path, headers, raw)
            else:
                import httpx

                r = httpx.request(method, self.base + path, headers=headers, content=raw or None, timeout=self.TIMEOUT)
                data = r.json()
        except Exception as exc:  # rede, timeout, JSON inválido
            log.warning("Tuya: falha de conexão (%s)", type(exc).__name__)
            raise ProviderError("Não consegui falar com a nuvem da Tuya (internet do notebook?).") from exc
        if not isinstance(data, dict) or not data.get("success"):
            code, msg = (data or {}).get("code"), str((data or {}).get("msg", ""))[:160]
            if code in (1010, 1011) and auth:  # token vencido: renova uma vez
                with self._lock:
                    self._token = None
            log.warning("Tuya: erro %s %s", code, msg)
            raise ProviderError(f"A Tuya recusou ({code}): {msg or 'sem detalhe'}")
        return data.get("result")

    def _get_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._token_exp - 60:
                return self._token
        res = self._send("GET", "/v1.0/token", {"grant_type": "1"}, auth=False)
        with self._lock:
            self._token = res["access_token"]
            self._token_exp = time.time() + int(res.get("expire_time", 3600))
            return self._token

    # aparelhos
    def list_devices(self, provider_uid: Optional[str]) -> list[RemoteDevice]:
        raw: list[dict] = []
        if provider_uid:
            raw = self._send("GET", f"/v1.0/users/{provider_uid}/devices") or []
        else:
            last = ""
            for _ in range(20):  # paginação (até 2000 aparelhos)
                q = {"size": "100"} | ({"last_row_key": last} if last else {})
                res = self._send("GET", "/v1.0/iot-01/associated-users/devices", q) or {}
                raw.extend(res.get("devices", []))
                if not res.get("has_more"):
                    break
                last = res.get("last_row_key", "")
        # 1º os controles dentro dos aparelhinhos infravermelhos (TV, ar)...
        out: list[RemoteDevice] = []
        for d in raw:
            if str(d.get("category", "")) in IR_HUB_CATS:
                for r in self._ir_remotes(d):
                    r.meta.setdefault("uid", d.get("uid", ""))
                    out.append(r)
        ir_ids = {r.provider_id for r in out}
        # ... depois o resto. A Tuya também lista cada controle IR como aparelho solto (categoria
        # "infrared_*", mesmo id): esses ficam de fora, o certo é o que veio pelo aparelhinho.
        for d in raw:
            cat = str(d.get("category", ""))
            if cat in IR_HUB_CATS or str(d.get("id")) in ir_ids or cat.startswith("infrared"):
                continue
            st, meta = normalize_status(d.get("status") or [])
            meta["uid"] = d.get("uid", "")
            out.append(RemoteDevice(str(d["id"]), str(d.get("name", "Aparelho")), cat, kind_for(cat),
                                    bool(d.get("online", True)), st, None, meta))
        return out

    def _ir_remotes(self, hub: dict) -> list[RemoteDevice]:
        """Controles (TV, ar) cadastrados dentro do aparelhinho infravermelho."""
        try:
            remotes = self._send("GET", f"/v2.0/infrareds/{hub['id']}/remotes") or []
        except ProviderError:
            return []
        out = []
        for r in remotes:
            cid = int(r.get("category_id", 0) or 0)
            name = str(r.get("remote_name") or r.get("brand_name") or "Controle")
            low = name.lower()
            kind = "ac" if cid in IR_AC_CATEGORY_IDS or "ar" in low.split() or "air" in low else \
                   "tv" if cid in IR_TV_CATEGORY_IDS or "tv" in low else "other"
            state = {"on": False} | ({"ac_temp": 24, "ac_mode": "frio", "ac_fan": 0} if kind == "ac" else {})
            out.append(RemoteDevice(str(r["remote_id"]), name, f"infrared_{kind}", kind, bool(hub.get("online", True)),
                                    state, str(hub["id"]), {"category_id": cid}))
        return out

    def act(self, device: Any, action: dict) -> dict:
        a, meta, kind = action.get("do"), dict(device.meta or {}), device.kind
        if device.parent_id:  # infravermelho: a Tuya não informa estado; guardamos o último comando
            self._ir(device, action)
            return apply_locally(kind, dict(device.state or {}), action)
        cmds = []
        sw = meta.get("switch_code", "switch_led" if kind == "light" else "switch_1")
        if a in ("on", "off"):
            cmds.append({"code": sw, "value": a == "on"})
        elif a == "bright":
            top = int(meta.get("bright_top", 1000))
            cmds += [{"code": sw, "value": True},
                     {"code": meta.get("bright_code", "bright_value_v2"), "value": max(10, round(int(action["value"]) * top / 100))}]
        elif a == "white":
            top = int(meta.get("white_top", 1000))
            cmds += [{"code": sw, "value": True}, {"code": "work_mode", "value": "white"},
                     {"code": meta.get("white_code", "temp_value_v2"), "value": round(WHITE[action["value"]] * top / 1000)}]
        else:
            raise ProviderError("Esse aparelho não aceita esse comando.")
        self._send("POST", f"/v1.0/devices/{device.provider_id}/commands", body={"commands": cmds})
        return apply_locally(kind, dict(device.state or {}), action)

    def _ir(self, device: Any, action: dict) -> None:
        hub, rid = device.parent_id, device.provider_id
        a = action.get("do")
        if device.kind == "ac":
            st = dict(device.state or {})
            body = {"power": 0 if a == "off" else 1,
                    "mode": AC_MODE.get(action.get("ac_mode", st.get("ac_mode", "frio")), 0),
                    "temp": int(action.get("ac_temp", st.get("ac_temp", 24))),
                    "wind": int(action.get("ac_fan", st.get("ac_fan", 0)))}
            self._send("POST", f"/v2.0/infrareds/{hub}/air-conditioners/{rid}/scenes/command", body=body)
            return
        key = "power" if a in ("on", "off") else action.get("value", "")
        if key not in TV_KEYS:
            raise ProviderError("Botão desconhecido para este controle.")
        cid = int((device.meta or {}).get("category_id", 2))
        self._send("POST", f"/v2.0/infrareds/{hub}/remotes/{rid}/command",
                   body={"category_id": cid, "key": TV_KEYS[key]})


def provider_for(settings) -> Any:
    if settings.casa_provider == "tuya":
        return TuyaProvider(settings.tuya_access_id.strip(), settings.tuya_access_secret.get_secret_value().strip(),
                            settings.tuya_region)
    return DemoProvider()

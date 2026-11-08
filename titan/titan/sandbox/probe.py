"""Sondagem (somente leitura) dos mecanismos de isolamento disponíveis no host.

Não executa código gerado. Os únicos comandos rodados são verificações
inofensivas (`--version`, `true` dentro de um namespace sem rede).
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path


def _run(cmd: list[str], timeout: int = 5) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, type(exc).__name__


def probe() -> dict:
    report: dict = {"arch": platform.machine(), "kernel": platform.release(), "checks": {}}
    c = report["checks"]

    bwrap = shutil.which("bwrap")
    if bwrap:
        rc, out = _run([bwrap, "--version"])
        c["bubblewrap"] = {"present": True, "version": out}
        rc, out = _run([bwrap, "--unshare-all", "--die-with-parent", "--ro-bind", "/usr", "/usr",
                        "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
                        "--symlink", "usr/lib64", "/lib64", "--proc", "/proc", "--dev", "/dev",
                        "/bin/true"])
        c["bubblewrap"]["works_unprivileged"] = rc == 0
        if rc != 0:
            c["bubblewrap"]["error"] = out[:200]
    else:
        c["bubblewrap"] = {"present": False}

    unshare = shutil.which("unshare")
    if unshare:
        rc, _ = _run([unshare, "--user", "--map-root-user", "--net", "true"])
        c["user_namespaces"] = {"works": rc == 0}
    max_ns = Path("/proc/sys/user/max_user_namespaces")
    if max_ns.exists():
        c.setdefault("user_namespaces", {})["max_user_namespaces"] = max_ns.read_text().strip()
    restrict = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
    if restrict.exists():
        c.setdefault("user_namespaces", {})["apparmor_restrict"] = restrict.read_text().strip()

    cg = Path("/sys/fs/cgroup/cgroup.controllers")
    c["cgroups_v2"] = {"present": cg.exists(),
                       "controllers": cg.read_text().split() if cg.exists() else []}
    c["systemd_run"] = {"present": bool(shutil.which("systemd-run"))}
    c["prlimit"] = {"present": bool(shutil.which("prlimit"))}
    status = Path("/proc/self/status")
    c["seccomp"] = {"supported": status.exists() and "Seccomp" in status.read_text()}

    for tool in ("podman", "docker"):
        path = shutil.which(tool)
        entry = {"present": bool(path)}
        if path:
            rc, out = _run([path, "info", "--format", "{{.Host.Security.Rootless}}" if tool == "podman"
                            else "{{.SecurityOptions}}"], timeout=10)
            entry["daemon_or_runtime_ok"] = rc == 0
            entry["info"] = out[:200]
        c[tool] = entry

    report["recommendation"] = _recommend(c)
    report["execution_enabled"] = False
    report["note"] = ("Somente sondagem. A execução continua desativada até um mecanismo passar "
                      "nos testes de fuga (docs/sandbox.md).")
    report["uid"] = os.getuid()
    return report


def _recommend(c: dict) -> str:
    if c.get("bubblewrap", {}).get("works_unprivileged"):
        return ("bubblewrap disponível e funcional sem root: candidato principal (leve, sem "
                "daemon), combinado com prlimit/systemd-run para limites.")
    if c.get("podman", {}).get("daemon_or_runtime_ok"):
        return "Podman disponível: candidato (rootless, sem daemon)."
    if c.get("user_namespaces", {}).get("works"):
        return ("user namespaces funcionam, mas bubblewrap não está instalado: instalar "
                "'bubblewrap' (pacote oficial, ~100 KB, exige sudo e sua autorização).")
    if c.get("docker", {}).get("daemon_or_runtime_ok"):
        return "Docker disponível: possível, porém mais pesado; exige configuração restritiva."
    return "Nenhum mecanismo de isolamento utilizável detectado: execução deve permanecer desativada."

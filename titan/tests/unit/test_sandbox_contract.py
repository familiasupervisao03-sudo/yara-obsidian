import pytest

from titan.config.settings import Settings
from titan.sandbox.contract import SandboxRequest, SandboxUnavailable, get_sandbox
from titan.sandbox.probe import probe


@pytest.mark.parametrize("enabled", [False, True])
def test_sandbox_always_refuses_in_this_version(enabled):
    s = Settings(_env_file=None, env="test", sandbox_enabled=enabled)
    sb = get_sandbox(s)
    with pytest.raises(SandboxUnavailable):
        sb.run(SandboxRequest(language="python", files={"main.py": "print(1)"}, command=["python", "main.py"]))


def test_default_limits_keep_network_off():
    assert SandboxRequest(language="python", files={}, command=[]).limits.network is False


def test_probe_is_report_only():
    r = probe()
    assert r["execution_enabled"] is False
    assert "recommendation" in r and "checks" in r

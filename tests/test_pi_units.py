"""The Pi's systemd units and scripts call commands the script really has."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

PI = Path(__file__).parents[1] / "pi"
_SPEC = importlib.util.spec_from_file_location("coppertrail_raw", PI / "coppertrail_raw.py")
raw = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(raw)


def subcommands() -> set[str]:
    ap = raw.parser()
    (sub,) = [a for a in ap._actions if a.dest == "command"]
    return set(sub.choices)


def test_units_call_existing_subcommands():
    services = sorted(PI.glob("*.service"))
    assert {p.name for p in services} == {"coppertrail-raw.service", "coppertrail-items.service"}
    for unit in services:
        (exec_start,) = re.findall(r"^ExecStart=(.+)$", unit.read_text(), re.M)
        assert exec_start.split()[-1] in subcommands(), unit.name
        assert "COPPERTRAIL_DB=/var/lib/coppertrail/raw.sqlite" in unit.read_text()


def test_every_timer_has_a_service():
    for timer in PI.glob("*.timer"):
        assert timer.with_suffix(".service").is_file(), timer.name


def test_timers_run_at_the_spec_minutes():
    assert "OnCalendar=*-*-* *:27:00 UTC" in (PI / "coppertrail-raw.timer").read_text()
    assert "OnCalendar=*-*-* *:00:00 UTC" in (PI / "coppertrail-items.timer").read_text()


def test_install_names_every_unit():
    install = (PI / "install.sh").read_text()
    for unit in [*PI.glob("*.service"), *PI.glob("*.timer")]:
        assert unit.name in install, unit.name


def test_secret_script_uses_the_check_subcommand():
    text = (PI / "set-blizzard-secret.sh").read_text()
    assert re.search(r"""\$SCRIPT'? check""", text)
    assert "--check" not in text

import pytest

from coppertrail.collector import __main__ as cli
from coppertrail.collector.config import Config
from coppertrail.collector.lock import RunLock


def test_unknown_command_exits_2_from_argparse(tmp_path):
    with pytest.raises(SystemExit) as e:
        cli.main(["--data-dir", str(tmp_path), "collect"])
    assert e.value.code == 2


def test_hourly_dispatches(monkeypatch, tmp_path):
    seen = []

    def fake_main(cfg):
        seen.append(cfg)
        return 0

    monkeypatch.setattr("coppertrail.collector.hourly.main", fake_main)
    assert cli.main(["--data-dir", str(tmp_path), "hourly"]) == 0
    assert isinstance(seen[0], Config) and seen[0].data_dir == tmp_path
    assert not (tmp_path / ".lock").exists()  # released after the run


def test_nightly_dispatches(monkeypatch, tmp_path):
    monkeypatch.setattr("coppertrail.collector.nightly.main", lambda cfg: 0)
    assert cli.main(["--data-dir", str(tmp_path), "nightly"]) == 0


def test_lock_held_exits_2(monkeypatch, tmp_path):
    monkeypatch.setattr("coppertrail.collector.hourly.main", lambda cfg: 0)
    held = RunLock(tmp_path / ".lock")
    held.acquire()
    try:
        assert cli.main(["--data-dir", str(tmp_path), "hourly"]) == 2
    finally:
        held.release()


def test_bad_config_exits_1(tmp_path):
    (tmp_path / "collector.toml").write_text("[selection]\nmax_itemz = 1\n")
    assert cli.main(["--data-dir", str(tmp_path), "hourly"]) == 1


def test_run_error_exits_1(monkeypatch, tmp_path):
    def boom(cfg):
        raise RuntimeError("no")

    monkeypatch.setattr("coppertrail.collector.hourly.main", boom)
    assert cli.main(["--data-dir", str(tmp_path), "hourly"]) == 1

import pytest


@pytest.fixture(autouse=True)
def config_dir(tmp_path, monkeypatch):
    """Never touch the real config folder (and its database) from a test."""
    d = tmp_path / "config"
    monkeypatch.setenv("COPPERTRAIL_CONFIG", str(d))
    return d

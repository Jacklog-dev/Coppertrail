import pytest

from tests.new_archive import SAMPLE_ITEMS, make_archive, sample_hours

ITEMS = SAMPLE_ITEMS


@pytest.fixture
def archive(tmp_path):
    """A small data folder: 9 items, each with the last 24 snapshots up to 16 Nov 07:00 UTC
    (lowest buyout and sales/day as in ITEMS), and Light Leather hourly from 9 Nov on."""
    return make_archive(tmp_path, [(i, n, c) for i, n, c, _, _ in ITEMS], sample_hours())


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    d = tmp_path / "config"
    monkeypatch.setenv("COPPERTRAIL_CONFIG", str(d))
    return d

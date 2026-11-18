import os
import time

import pytest

from coppertrail.collector.credentials import CredentialsError, load_credentials
from coppertrail.collector.lock import LockError, RunLock
from coppertrail.collector.throttle import Throttle, parse_retry_after


def _toml(folder):
    (folder / "blizzard.toml").write_text('[blizzard]\nclient_id="f"\nclient_secret="g"\n')


def test_env_wins(tmp_path):
    _toml(tmp_path)
    env = {"BLIZZARD_CLIENT_ID": "a", "BLIZZARD_CLIENT_SECRET": "b"}
    assert load_credentials(env, tmp_path) == ("a", "b")


def test_file_fallback(tmp_path):
    _toml(tmp_path)
    assert load_credentials({}, tmp_path) == ("f", "g")


def test_missing_names_sources_not_values(tmp_path):
    with pytest.raises(CredentialsError) as e:
        load_credentials({"BLIZZARD_CLIENT_ID": "only-id"}, tmp_path)
    msg = str(e.value)
    assert "BLIZZARD_CLIENT_SECRET" in msg and str(tmp_path / "blizzard.toml") in msg
    assert "only-id" not in msg


def test_incomplete_file_is_missing(tmp_path):
    (tmp_path / "blizzard.toml").write_text('[blizzard]\nclient_id="f"\n')
    with pytest.raises(CredentialsError):
        load_credentials({}, tmp_path)


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def test_throttle_spacing():
    c = FakeClock()
    th = Throttle(2.0, clock=c.clock, sleep=c.sleep)
    for _ in range(3):
        th.wait()
    assert c.sleeps == [2.0, 2.0]


def test_parse_retry_after():
    assert parse_retry_after("3", 9.0) == 3.0
    assert parse_retry_after(None, 9.0) == 9.0
    assert parse_retry_after("soon", 9.0) == 9.0


def test_lock_is_exclusive(tmp_path):
    a, b = RunLock(tmp_path / ".lock"), RunLock(tmp_path / ".lock")
    a.acquire()
    with pytest.raises(LockError):
        b.acquire()
    a.release()
    b.acquire()
    b.release()


def test_stale_lock_is_taken_over(tmp_path):
    path = tmp_path / ".lock"
    path.write_text("old")
    old = time.time() - 3600
    os.utime(path, (old, old))
    RunLock(path).acquire()
    assert "pid=" in path.read_text()

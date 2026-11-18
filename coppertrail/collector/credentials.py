"""Blizzard API credentials: environment first, then `blizzard.toml` in the config folder.

Messages name where credentials are looked for, never a value.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path

ENV_ID = "BLIZZARD_CLIENT_ID"
ENV_SECRET = "BLIZZARD_CLIENT_SECRET"


class CredentialsError(Exception):
    pass


def load_credentials(
    env: Mapping[str, str] = os.environ, folder: Path | None = None
) -> tuple[str, str]:
    cid, secret = env.get(ENV_ID), env.get(ENV_SECRET)
    if cid and secret:
        return cid, secret
    if folder is None:
        from coppertrail.query.settings import config_dir

        folder = config_dir()
    path = Path(folder) / "blizzard.toml"
    if path.exists():
        raw = tomllib.loads(path.read_text(encoding="utf-8")).get("blizzard", {})
        if raw.get("client_id") and raw.get("client_secret"):
            return str(raw["client_id"]), str(raw["client_secret"])
    raise CredentialsError(
        f"No Blizzard API credentials: set {ENV_ID} and {ENV_SECRET}, "
        f"or create {path} with a [blizzard] table (client_id, client_secret)."
    )

"""Which version of the app is running and where its code lives, for the info page of the settings.

A release image gets its version, commit and build date as build arguments (``docker/Dockerfile``,
``.github/workflows/build.yaml``), and the version is the one release-please wrote into ``pyproject.toml``
for that tag. Run from source, the version is read from ``pyproject.toml`` itself and there is no commit.
"""

import sqlite3
import tomllib
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from platform import python_version

import django

from config.env import ROOT_DIR, get_env

REPOSITORY_URL = "https://github.com/maki-it/LexTracker"
# release-please names the tag after the package.
TAG_PREFIX = "lextracker-v"
# The default of the Docker build argument, an image that was built by hand.
UNRELEASED = "dev"


@dataclass(frozen=True)
class Info:
    version: str
    # Built for a release (and so has a page on GitHub), not run from source or built by hand.
    released: bool
    commit: str
    built_at: datetime | None
    python: str
    django: str
    sqlite: str

    @property
    def short_commit(self) -> str:
        return self.commit[:7]

    @property
    def commit_url(self) -> str:
        return f"{REPOSITORY_URL}/commit/{self.commit}" if self.commit else ""

    @property
    def release_url(self) -> str:
        return f"{REPOSITORY_URL}/releases/tag/{TAG_PREFIX}{self.version}" if self.released else ""


def _project_version() -> str:
    try:
        with (ROOT_DIR / "pyproject.toml").open("rb") as file:
            return tomllib.load(file)["project"]["version"]
    except OSError, KeyError, tomllib.TOMLDecodeError:
        # Not part of the image, which only carries the app folder.
        return UNRELEASED


def _built_at(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


@cache
def load() -> Info:
    env = get_env()
    released = env.version not in ("", UNRELEASED)
    return Info(
        version=env.version if released else _project_version(),
        released=released,
        commit=env.commit,
        built_at=_built_at(env.build_date),
        python=python_version(),
        django=django.get_version(),
        sqlite=sqlite3.sqlite_version,
    )

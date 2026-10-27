"""Felles testoppsett: config fra repoet og en FakeHttp som svarer fra fiksturer."""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from collector.__main__ import load_config  # noqa: E402


class FakeHttp:
    """Svarer med fikstur per URL-prefiks; ukjent URL → RuntimeError som en ekte feil."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, url, params=None, headers=None, kind="json"):
        self.calls.append((url, params))
        for prefix, payload in self.routes.items():
            if url.startswith(prefix):
                if callable(payload):
                    return payload(url, params, headers, kind)
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise RuntimeError(f"GET {url} feilet: ingen fikstur")


@pytest.fixture
def cfg():
    return load_config(os.path.join(ROOT, "config.yaml"))

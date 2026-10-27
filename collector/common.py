"""Felles byggeklosser for innsamleren.

Alle kildemoduler bruker Http til å hente, og returnerer en SourceResult med
normaliserte data og en liste av Signal-objekter. Aggregatoren (status.py)
regner trafikklys per kategori ut fra signalene.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import requests

log = logging.getLogger("collector")

# Nivåer for trafikklys
UNKNOWN, GREEN, YELLOW, RED = -1, 0, 1, 2
LEVEL_NAME = {UNKNOWN: "unknown", GREEN: "green", YELLOW: "yellow", RED: "red"}

# Kategorier på forsiden
CATEGORIES = ["strom", "vann", "ekom", "betaling", "transport", "varsler", "lokalt", "naboland"]


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def now_iso() -> str:
    return now_utc().isoformat()


def epoch_ms_to_iso(value: Any) -> Optional[str]:
    """ArcGIS og Statnett bruker epoch i millisekunder."""
    if value in (None, "", 0):
        return None
    try:
        return dt.datetime.fromtimestamp(int(value) / 1000, tz=dt.timezone.utc).replace(microsecond=0).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def parse_iso(value: Any) -> Optional[dt.datetime]:
    """Tåler 'Z', manglende tidssone og feedparser-structs."""
    if not value:
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    if isinstance(value, time.struct_time):
        return dt.datetime.fromtimestamp(time.mktime(value), tz=dt.timezone.utc)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).replace(",", ".").strip()))
    except (TypeError, ValueError):
        return default


def to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return default


def entry_get(entry: Any, key: str) -> Any:
    """feedparser mapper 'updated'→'published' med advarsel; slå opp uten den magien."""
    try:
        return entry[key] if key in entry.keys() else None
    except AttributeError:
        return entry.get(key)


def truncate(text: Any, n: int = 300) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


@dataclass
class Signal:
    category: str
    level: int
    text: str
    source: str
    url: str = ""
    since: Optional[str] = None
    value: Optional[float] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["level_name"] = LEVEL_NAME.get(self.level, "unknown")
        return d


@dataclass
class SourceResult:
    id: str
    name: str
    url: str
    category: str
    ok: bool = False
    fetched_at: str = field(default_factory=now_iso)
    last_success_at: Optional[str] = None
    stale: bool = False
    error: str = ""
    license: str = ""
    data: dict = field(default_factory=dict)
    signals: list[Signal] = field(default_factory=list)

    def fail(self, error: str) -> "SourceResult":
        self.ok = False
        self.error = truncate(error, 400)
        log.warning("%s: %s", self.id, self.error)
        return self

    def succeed(self) -> "SourceResult":
        self.ok = True
        self.error = ""
        self.last_success_at = self.fetched_at
        return self

    def add(self, level: int, text: str, category: Optional[str] = None, **kw) -> None:
        self.signals.append(Signal(category or self.category, level, text, self.id, kw.pop("url", self.url), **kw))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "category": self.category,
            "ok": self.ok,
            "stale": self.stale,
            "fetched_at": self.fetched_at,
            "last_success_at": self.last_success_at,
            "error": self.error,
            "license": self.license,
            "data": self.data,
            "signals": [s.to_dict() for s in self.signals],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SourceResult":
        r = cls(d["id"], d["name"], d["url"], d.get("category", "varsler"))
        r.ok = bool(d.get("ok"))
        r.stale = bool(d.get("stale"))
        r.fetched_at = d.get("fetched_at") or now_iso()
        r.last_success_at = d.get("last_success_at")
        r.error = d.get("error", "")
        r.license = d.get("license", "")
        r.data = d.get("data", {})
        r.signals = [
            Signal(s["category"], int(s["level"]), s["text"], s["source"], s.get("url", ""), s.get("since"), s.get("value"))
            for s in d.get("signals", [])
        ]
        return r


class Http:
    """Liten HTTP-klient med User-Agent, timeout og nye forsøk.

    Kildene krever gjerne en identifiserende User-Agent (MET avviser uten),
    og Entur gir høyere kvote med ET-Client-Name. Begge settes i config.
    """

    def __init__(self, user_agent: str, timeout: int = 20, retries: int = 2, extra_headers: Optional[dict] = None):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "*/*"})
        if extra_headers:
            self.session.headers.update(extra_headers)
        self.timeout = timeout
        self.retries = retries

    def get(self, url: str, params: Optional[dict] = None, headers: Optional[dict] = None, kind: str = "json") -> Any:
        last_err: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                resp = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
                if resp.status_code == 429 and attempt < self.retries:
                    time.sleep(2 + 3 * attempt)
                    continue
                resp.raise_for_status()
                if kind == "json":
                    return resp.json()
                if kind == "bytes":
                    return resp.content
                return resp.text
            except (requests.RequestException, ValueError) as e:  # ValueError = ugyldig JSON
                last_err = e
                if attempt < self.retries:
                    time.sleep(1 + attempt)
        raise RuntimeError(f"GET {url} feilet: {last_err}")

    def post_json(self, url: str, payload: dict, headers: Optional[dict] = None) -> Any:
        resp = self.session.post(url, json=payload, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()


def dump_json(path, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=False)
        f.write("\n")


def load_json(path) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None

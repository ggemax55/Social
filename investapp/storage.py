"""Saving and loading your data: a local JSON file, or a private GitHub repository so that
every device (PC, iPhone) sees the same data."""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .buckets import DEFAULT_SPLIT
from .data import ARMENIA_STARTER, MARKET_OVERVIEW
from .fees import Broker
from .money import fx_ticker
from .planner import Plan
from .portfolio import Transaction

DEFAULT_PATH = Path(
    os.environ.get("INVESTAPP_DATA", Path(__file__).resolve().parent.parent / "data" / "portfolio.json")
)


@dataclass
class AppState:
    currency: str = "USD"  # trading currency: prices, trades and holdings
    watchlist: list[str] = field(default_factory=lambda: ["SPY", "QQQ", "VT", "VTI", "VXUS", "BND"])
    transactions: list[Transaction] = field(default_factory=list)
    plans: list[Plan] = field(default_factory=list)
    market_overview: list[str] = field(default_factory=lambda: [*MARKET_OVERVIEW, "AMD=X"])
    country: str = "Armenia"
    home_currency: str = "AMD"  # amounts are also shown in this currency
    broker: dict = field(default_factory=lambda: Broker().to_dict())
    allowed_tickers: list[str] = field(default_factory=lambda: list(ARMENIA_STARTER))
    task_log: dict[str, dict] = field(default_factory=dict)  # task key -> {"status", "date"}
    bucket_split: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SPLIT))  # % per section
    telegram: dict = field(default_factory=lambda: {"token": "", "chat_id": "", "name": ""})
    app_url: str = ""  # link to the app, included in reminders

    def to_dict(self) -> dict:
        return {
            "currency": self.currency,
            "country": self.country,
            "home_currency": self.home_currency,
            "broker": self.broker,
            "allowed_tickers": self.allowed_tickers,
            "watchlist": self.watchlist,
            "market_overview": self.market_overview,
            "transactions": [t.to_dict() for t in self.transactions],
            "plans": [p.to_dict() for p in self.plans],
            "task_log": self.task_log,
            "bucket_split": self.bucket_split,
            "telegram": self.telegram,
            "app_url": self.app_url,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AppState":
        default = cls()
        return cls(
            currency=d.get("currency", default.currency),
            country=d.get("country", default.country),
            home_currency=d.get("home_currency", default.home_currency).upper(),
            broker=d.get("broker", default.broker),
            allowed_tickers=[s.upper() for s in d.get("allowed_tickers", default.allowed_tickers)],
            watchlist=[s.upper() for s in d.get("watchlist", default.watchlist)],
            market_overview=d.get("market_overview", default.market_overview),
            transactions=[Transaction.from_dict(t) for t in d.get("transactions", [])],
            plans=[Plan.from_dict(p) for p in d.get("plans", [])],
            task_log=dict(d.get("task_log", {})),
            bucket_split=dict(d.get("bucket_split", default.bucket_split)),
            telegram={**default.telegram, **d.get("telegram", {})},
            app_url=d.get("app_url", ""),
        )

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram.get("token") and self.telegram.get("chat_id"))

    @property
    def broker_profile(self) -> Broker:
        return Broker.from_dict(self.broker)

    def plan_by_id(self, plan_id: str) -> Plan | None:
        return next((p for p in self.plans if p.id == plan_id), None)

    def add_plan(self, plan: Plan) -> Plan:
        """Add a plan, making sure its id is unique."""
        base, n = plan.id, 1
        while any(p.id == plan.id for p in self.plans):
            plan.id = f"{base}-{n}"
            n += 1
        self.plans.append(plan)
        return plan

    def all_tickers(self) -> list[str]:
        tickers = set(self.watchlist) | {t.ticker for t in self.transactions}
        for p in self.plans:
            tickers |= set(p.targets)
        for cur in {self.home_currency, *(p.currency for p in self.plans)}:
            if fx_ticker(cur):
                tickers.add(fx_ticker(cur))
        return sorted(tickers)


def to_json(state: AppState) -> str:
    return json.dumps(state.to_dict(), indent=2)


def from_json(text: str) -> AppState:
    return AppState.from_dict(json.loads(text))


def load_state(path: Path | str | None = None) -> AppState:
    path = Path(path or DEFAULT_PATH)
    if not path.exists():
        return AppState()
    return from_json(path.read_text())


def save_state(state: AppState, path: Path | str | None = None) -> None:
    path = Path(path or DEFAULT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(to_json(state))
    tmp.replace(path)


# ---------------------------------------------------------------- stores


class ConflictError(RuntimeError):
    """The data was changed on another device after it was loaded here."""


class LocalStore:
    """Data in a file on this computer."""

    kind = "local"

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or DEFAULT_PATH)

    def describe(self) -> str:
        return "This computer only"

    def load(self) -> tuple[AppState, str | None]:
        return load_state(self.path), None

    def remote_version(self) -> str | None:
        return None

    def save(self, state: AppState, version: str | None) -> str | None:
        save_state(state, self.path)
        return None


def _github(method: str, url: str, token: str, body: dict | None = None, timeout: float = 15) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "InvestTrack",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read() or b"{}")
        except ValueError:
            payload = {}
        return e.code, payload


class GitHubStore:
    """Data in a file of a private GitHub repository, shared by all your devices.

    Every save is a commit, so the repository also keeps a full history. Saving
    checks the file hasn't changed since it was loaded and raises ConflictError
    if it has, so one device never silently overwrites another's changes.
    """

    kind = "github"

    def __init__(self, token: str, repo: str, path: str = "portfolio.json", branch: str | None = None):
        self.token, self.repo, self.path, self.branch = token, repo.strip(), path.strip("/") or "portfolio.json", branch
        self.url = f"https://api.github.com/repos/{self.repo}/contents/{self.path}"

    def describe(self) -> str:
        return f"Synced with GitHub ({self.repo})"

    def _get(self) -> tuple[int, dict]:
        url = self.url + (f"?ref={self.branch}" if self.branch else "")
        status, payload = _github("GET", url, self.token)
        if status not in (200, 404):
            raise OSError(f"GitHub returned {status}: {payload.get('message', '')}")
        return status, payload

    def load(self) -> tuple[AppState, str | None]:
        status, payload = self._get()
        if status == 404:
            return AppState(), None  # first use: the file is created on the first save
        text = base64.b64decode(payload["content"]).decode("utf-8")
        return from_json(text), payload["sha"]

    def remote_version(self) -> str | None:
        status, payload = self._get()
        return payload.get("sha") if status == 200 else None

    def save(self, state: AppState, version: str | None) -> str | None:
        body = {
            "message": "InvestTrack: update data",
            "content": base64.b64encode(to_json(state).encode("utf-8")).decode("ascii"),
        }
        if version:
            body["sha"] = version
        if self.branch:
            body["branch"] = self.branch
        status, payload = _github("PUT", self.url, self.token, body)
        if status in (409, 422):  # file changed since loaded (or created elsewhere)
            raise ConflictError("Your data was changed on another device.")
        if status not in (200, 201):
            raise OSError(f"GitHub returned {status}: {payload.get('message', '')}")
        return payload["content"]["sha"]


def make_store(config: dict | None = None) -> LocalStore | GitHubStore:
    """GitHubStore when a token and repository are configured, otherwise LocalStore.

    `config` keys: token, repo, path (optional). Without `config`, the environment
    variables INVESTAPP_GITHUB_TOKEN, INVESTAPP_GITHUB_REPO and INVESTAPP_GITHUB_PATH are used.
    """
    if config is None:
        config = {
            "token": os.environ.get("INVESTAPP_GITHUB_TOKEN", ""),
            "repo": os.environ.get("INVESTAPP_GITHUB_REPO", ""),
            "path": os.environ.get("INVESTAPP_GITHUB_PATH", "portfolio.json"),
        }
    if config.get("token") and config.get("repo"):
        return GitHubStore(config["token"], config["repo"], config.get("path") or "portfolio.json")
    return LocalStore()

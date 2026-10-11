import base64
import json

import pandas as pd
import pytest

from investapp import notify, storage
from investapp.actions import Task
from investapp.ics import plans_calendar
from investapp.planner import Plan
from investapp.storage import AppState, ConflictError, GitHubStore, LocalStore, make_store


class FakeGitHub:
    """In-memory stand-in for the GitHub contents API."""

    def __init__(self):
        self.files: dict[str, tuple[str, str]] = {}  # url -> (content, sha)
        self.n = 0

    def __call__(self, method, url, token, body=None, timeout=15):
        assert token == "tok"
        url = url.split("?")[0]
        if method == "GET":
            if url not in self.files:
                return 404, {"message": "Not Found"}
            content, sha = self.files[url]
            return 200, {"sha": sha, "content": base64.b64encode(content.encode()).decode()}
        current = self.files.get(url)
        if current and body.get("sha") != current[1]:
            return 409, {"message": "does not match"}
        if not current and body.get("sha"):
            return 409, {"message": "does not match"}
        if current is None and "sha" not in body and url in self.files:
            return 422, {"message": "sha wasn't supplied"}
        self.n += 1
        sha = f"sha{self.n}"
        self.files[url] = (base64.b64decode(body["content"]).decode(), sha)
        return (200 if current else 201), {"content": {"sha": sha}}


@pytest.fixture
def github(monkeypatch):
    fake = FakeGitHub()
    monkeypatch.setattr(storage, "_github", fake)
    return fake


def test_github_store_round_trip_and_conflicts(github):
    phone = GitHubStore("tok", "me/data")
    state, version = phone.load()
    assert version is None and state.plans == []  # first use: nothing stored yet
    state.plans.append(Plan("Long", 20000, "monthly", {"VT": 1}, currency="AMD", bucket="long"))
    v1 = phone.save(state, version)

    pc = GitHubStore("tok", "me/data")
    pc_state, pc_version = pc.load()
    assert pc_version == v1 and pc_state.plans[0].name == "Long"
    assert pc.remote_version() == v1

    pc_state.app_url = "https://x"
    v2 = pc.save(pc_state, pc_version)
    assert v2 != v1
    with pytest.raises(ConflictError):  # the phone still has the old version
        phone.save(state, v1)
    fresh, fresh_version = phone.load()
    assert fresh.app_url == "https://x" and fresh_version == v2


def test_make_store(monkeypatch, tmp_path):
    monkeypatch.delenv("INVESTAPP_GITHUB_TOKEN", raising=False)
    assert isinstance(make_store(), LocalStore)
    assert isinstance(make_store({"token": "t", "repo": "me/data"}), GitHubStore)
    monkeypatch.setenv("INVESTAPP_GITHUB_TOKEN", "t")
    monkeypatch.setenv("INVESTAPP_GITHUB_REPO", "me/data")
    store = make_store()
    assert isinstance(store, GitHubStore) and store.path == "portfolio.json"
    local = LocalStore(tmp_path / "p.json")
    state, _ = local.load()
    state.telegram["chat_id"] = "42"
    local.save(state, None)
    assert local.load()[0].telegram["chat_id"] == "42"


def test_reminder_text_lists_tasks_by_section():
    orders = pd.DataFrame({"ticker": ["VT", "BND"], "shares": [0.4331, 2.0], "price": [160, 70], "amount": [69, 140],
                           "fee": [0.35, 0.35]})
    tasks = [
        Task("a", "buy", "Buy for “Long”: 25,000 AMD", "", 0, orders=orders, bucket="long"),
        Task("b", "save", "Set aside 1,000 AMD for “Short”", "", 0, bucket="short"),
        Task("c", "routine", "Weekly check-in", "", 2),
    ]
    text = notify.reminder_text(tasks, "2026-10-12", "https://app")
    assert "2 thing(s) to do" in text
    assert "🌳 🛒 Buy for “Long”: 25,000 AMD → buy 0.4331 VT, 2 BND" in text
    assert "🍞 💰 Set aside" in text and "Optional: Weekly check-in" in text and "https://app" in text
    assert notify.reminder_text([]) is None


def test_telegram_helpers(monkeypatch):
    calls = []

    def fake_call(token, method, payload=None, timeout=15):
        calls.append((method, payload))
        if method == "getUpdates":
            return {"ok": True, "result": [{"update_id": 1, "message": {"chat": {"id": 777, "first_name": "Will"}}}]}
        return {"ok": True}

    monkeypatch.setattr(notify, "_call", fake_call)
    assert notify.find_chat("x") == ("777", "Will")
    notify.send("x", "777", "hi")
    assert calls[-1] == ("sendMessage", {"chat_id": "777", "text": "hi", "disable_web_page_preview": True})
    assert notify.valid_token("123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw")
    assert not notify.valid_token("not a token")


def test_notify_cli_without_telegram(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(storage, "DEFAULT_PATH", tmp_path / "none.json")
    monkeypatch.delenv("INVESTAPP_GITHUB_TOKEN", raising=False)
    assert notify.main([]) == 0
    assert "not set up" in capsys.readouterr().out


def test_calendar_file():
    plans = [
        Plan("Short", 1000, "daily", {"SGOV": 1}, start_date="2026-10-12", currency="AMD", bucket="short"),
        Plan("Income", 12000, "weekly", {"BND": 1}, start_date="2026-10-14", currency="AMD", bucket="income"),
        Plan("Long", 25000, "monthly", {"VT": 1}, start_date="2026-10-31", currency="AMD", bucket="long"),
        Plan("Paused", 1, "monthly", {"VT": 1}, active=False),
    ]
    ics = plans_calendar(plans, "https://app")
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert ics.count("BEGIN:VEVENT") == 3
    assert "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR" in ics
    assert "RRULE:FREQ=WEEKLY;BYDAY=WE" in ics
    assert "RRULE:FREQ=MONTHLY;BYMONTHDAY=-1" in ics  # the 31st becomes "last day of the month"
    assert "SUMMARY:InvestTrack: Long (25\\,000 AMD)" in ics
    assert "TRIGGER:PT9H" in ics


def test_state_keeps_new_fields():
    s = AppState()
    s.bucket_split = {"short": 10, "income": 20, "long": 70}
    s.telegram = {"token": "t", "chat_id": "1", "name": "W"}
    s.app_url = "https://a"
    back = storage.from_json(storage.to_json(s))
    assert back.bucket_split == s.bucket_split and back.telegram_ready and back.app_url == "https://a"
    old = storage.from_json(json.dumps({"plans": []}))
    assert old.bucket_split == {"short": 20, "income": 30, "long": 50} and not old.telegram_ready

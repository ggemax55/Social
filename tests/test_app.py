"""Smoke tests: run the whole Streamlit app offline on synthetic prices."""

import json
import zlib

import numpy as np
import pandas as pd
import pytest

import investapp.data

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
TODAY = str(pd.Timestamp.today().date())


def fake_prices(tickers, period="2y"):
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=1500)
    cols = {}
    for t in tickers:
        rng = np.random.default_rng(zlib.crc32(t.encode()))
        if t.endswith("=X"):  # exchange rates: stable around 400
            cols[t.upper()] = 400.0 * np.exp(rng.normal(0, 0.002, len(idx)))
        else:
            cols[t.upper()] = 100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, len(idx))))
    return pd.DataFrame(cols, index=idx)


def make_app(tmp_path, monkeypatch, data: dict):
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr("investapp.storage.DEFAULT_PATH", path)
    monkeypatch.setattr(investapp.data, "fetch_prices", fake_prices)
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at, path


IBKR = {"name": "Interactive Brokers (direct account)", "per_share": 0.0035, "min_fee": 0.35, "max_pct": 0.01,
        "fractional": True}


def test_new_user_sees_setup_tasks_and_all_tabs(tmp_path, monkeypatch):
    at, _ = make_app(tmp_path, monkeypatch, {})
    assert len(at.tabs) >= 10
    titles = " ".join(m.value for m in at.markdown)
    assert "Choose your broker" in titles
    assert "Create your daily, weekly and monthly plans" in titles


def test_quick_start_creates_three_plans(tmp_path, monkeypatch):
    freedom = {"name": "Freedom Broker Armenia", "pct": 0.0012, "min_fee": 1.2, "fractional": False}
    at, path = make_app(tmp_path, monkeypatch, {"broker": freedom})
    next(n for n in at.number_input if n.label == "Monthly budget (AMD)").set_value(200_000.0)
    next(b for b in at.button if b.label == "Create these plans").click().run()
    assert not at.exception
    plans = json.loads(path.read_text())["plans"]
    assert [p["frequency"] for p in plans] == ["daily", "weekly", "monthly"]
    assert all(p["currency"] == "AMD" for p in plans)
    daily = plans[0]
    assert daily["buy_threshold"] > daily["amount"]  # small daily amounts are saved up before buying
    titles = " ".join(m.value for m in at.markdown)
    assert "Set aside" in titles and "Buy for" in titles


def test_buy_task_records_purchase(tmp_path, monkeypatch):
    plan = {"name": "Core", "amount": 40000, "currency": "AMD", "frequency": "weekly",
            "targets": {"VT": 80, "BND": 20}, "start_date": TODAY}
    at, path = make_app(tmp_path, monkeypatch, {"broker": IBKR, "plans": [plan]})
    next(b for b in at.button if b.label == "✅ Done: I bought these").click().run()
    assert not at.exception
    saved = json.loads(path.read_text())
    assert {t["ticker"] for t in saved["transactions"]} == {"VT", "BND"}
    assert all(t["note"] == "Plan: Core" for t in saved["transactions"])
    assert any(k.endswith(TODAY) for k in saved["task_log"])
    assert not [b for b in at.button if b.label == "✅ Done: I bought these"]


def test_backtest_with_fees_and_broker_switch(tmp_path, monkeypatch):
    at, path = make_app(tmp_path, monkeypatch, {"broker": IBKR})
    next(b for b in at.button if b.label == "Run backtest").click().run()
    assert not at.exception
    assert any(m.label == "Fees paid (USD)" for m in at.metric)

    broker_box = next(s for s in at.selectbox if s.label == "Broker you use (or plan to use)")
    broker_box.select("Freedom Broker Armenia").run()
    assert not at.exception
    assert json.loads(path.read_text())["broker"]["name"] == "Freedom Broker Armenia"

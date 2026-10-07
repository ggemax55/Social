"""Smoke test: run the whole Streamlit app offline on synthetic prices."""

import json
import zlib

import numpy as np
import pandas as pd
import pytest

import investapp.data

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def fake_prices(tickers, period="2y"):
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=1500)
    cols = {}
    for t in tickers:
        rng = np.random.default_rng(zlib.crc32(t.encode()))
        cols[t.upper()] = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(idx))))
    return pd.DataFrame(cols, index=idx)


@pytest.fixture
def app(tmp_path, monkeypatch):
    data = {
        "transactions": [
            {"date": "2025-01-06", "ticker": "VTI", "side": "buy", "shares": 3, "price": 100},
            {"date": "2025-06-02", "ticker": "BND", "side": "buy", "shares": 5, "price": 100},
        ],
        "plans": [
            {"name": "Core", "amount": 200, "frequency": "monthly",
             "targets": {"VTI": 60, "BND": 40}, "start_date": "2025-01-06"},
        ],
    }
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps(data))
    monkeypatch.setenv("INVESTAPP_DATA", str(path))
    monkeypatch.setattr("investapp.storage.DEFAULT_PATH", path)
    monkeypatch.setattr(investapp.data, "fetch_prices", fake_prices)
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.run()
    return at, path


def test_app_renders_all_tabs(app):
    at, _ = app
    assert not at.exception
    assert len(at.tabs) == 8
    labels = [m.label for m in at.metric]
    assert "Portfolio value (USD)" in labels
    assert any("Core" in e.label for e in at.expander)


def test_backtest_and_record_plan_buys(app):
    at, path = app
    next(b for b in at.button if b.label == "Run backtest").click().run()
    assert not at.exception
    assert any(m.label.startswith("Would be worth") for m in at.metric)

    next(b for b in at.button if b.label == "I bought these: record them").click().run()
    assert not at.exception
    saved = json.loads(path.read_text())
    assert len(saved["transactions"]) > 2
    assert all(t["note"] == "Plan: Core" for t in saved["transactions"][2:])
    assert saved["plans"][0]["last_done"] == str(pd.Timestamp.today().date())

import io
import json
import zipfile

import pandas as pd
import pytest

from investapp import updater
from investapp.imports import guess_mapping, merge_trades, parse_trades, read_csv
from investapp.portfolio import Transaction


def test_ibkr_style_csv_import():
    csv = (
        "Symbol,Date/Time,Quantity,T. Price,Comm/Fee\n"
        "VT,\"2026-10-01, 10:31:02\",2,110.5,-0.35\n"
        "BND,2026-10-02,-1,72.1,-0.35\n"
        ",2026-10-03,1,10,0\n"
    )
    df = read_csv(csv)
    mapping = guess_mapping(df.columns)
    assert mapping == {"date": "Date/Time", "ticker": "Symbol", "side": None, "shares": "Quantity",
                       "price": "T. Price", "fee": "Comm/Fee"}
    trades, problems = parse_trades(df, mapping)
    assert [(t.date, t.ticker, t.side, t.shares, t.price, t.fee) for t in trades] == [
        ("2026-10-01", "VT", "buy", 2.0, 110.5, 0.35),
        ("2026-10-02", "BND", "sell", 1.0, 72.1, 0.35),
    ]
    assert len(problems) == 1 and "Line 4" in problems[0]


def test_side_column_and_semicolon_csv():
    df = read_csv("date;ticker;operation;qty;price\n07.10.2026;voo;Buy;1,5;600\n08.10.2026;VOO;Sell;0.5;610\n")
    mapping = guess_mapping(df.columns)
    assert mapping["side"] == "operation"
    trades, problems = parse_trades(df, mapping)
    assert not problems
    assert [(t.date, t.ticker, t.side, t.shares) for t in trades] == [
        ("2026-10-07", "VOO", "buy", 1.5), ("2026-10-08", "VOO", "sell", 0.5)
    ]


def test_number_formats():
    from investapp.imports import _number
    assert _number("1,234.56") == 1234.56
    assert _number("1.234,56") == 1234.56
    assert _number("1,234") == 1234
    assert _number("72,10") == 72.1
    assert _number("(0.35)") == -0.35
    assert _number("$1,000") == 1000


def test_missing_required_columns():
    trades, problems = parse_trades(pd.DataFrame({"a": [1]}), {"date": None, "ticker": None, "shares": None, "price": None})
    assert not trades and "Choose a column" in problems[0]


def test_merge_skips_duplicates():
    a = Transaction("2026-10-01", "VT", "buy", 2, 110.5)
    b = Transaction("2026-10-02", "VT", "buy", 1, 111)
    merged, added, dupes = merge_trades([a], [a, b, b])
    assert (len(merged), added, dupes) == (2, 1, 2)


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(f"Social-abc123/{name}", text)
    return buf.getvalue()


def test_updater_replaces_code_and_keeps_data(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "portfolio.json").write_text("MY DATA")
    (tmp_path / "app.py").write_text("old")
    monkeypatch.setattr(updater, "ROOT", tmp_path)
    monkeypatch.setattr(updater, "VERSION_FILE", tmp_path / ".version")
    archive = _zip({"app.py": "new", "investapp/x.py": "x", "data/portfolio.json": "UPSTREAM"})

    def fake_get(url, timeout):
        if url == updater.API:
            return json.dumps({"default_branch": "main"}).encode()
        if url.endswith("/commits/main"):
            return json.dumps({"sha": "abc123"}).encode()
        return archive

    monkeypatch.setattr(updater, "_get", fake_get)
    assert updater.update_available() is True
    assert updater.run() is True
    assert (tmp_path / "app.py").read_text() == "new"
    assert (tmp_path / "investapp" / "x.py").read_text() == "x"
    assert (tmp_path / "data" / "portfolio.json").read_text() == "MY DATA"
    assert updater.local_version() == "abc123"
    assert updater.update_available() is False
    assert updater.run() is False


def test_updater_leaves_git_checkouts_alone(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(updater, "ROOT", tmp_path)
    assert updater.update_available() is None
    assert updater.run() is False


def test_updater_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "ROOT", tmp_path)

    def offline(url, timeout):
        raise OSError("no network")

    monkeypatch.setattr(updater, "_get", offline)
    assert updater.update_available() is None
    assert updater.run() is False

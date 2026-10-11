"""Reminders on your phone through a Telegram bot.

    python -m investapp.notify            # send today's to-do list (only if there is something to do)
    python -m investapp.notify --test     # send a test message
    python -m investapp.notify --dry-run  # print the message instead of sending it

Data is read from the private GitHub repository when INVESTAPP_GITHUB_TOKEN and
INVESTAPP_GITHUB_REPO are set (that's how the daily GitHub Actions reminder runs),
otherwise from data/portfolio.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd

from .buckets import BUCKETS

TELEGRAM_API = "https://api.telegram.org"
TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
TASK_ICONS = {"setup": "⚙️", "buy": "🛒", "save": "💰", "extra": "✨", "review": "⚖️", "routine": "📅"}


class NotifyError(RuntimeError):
    pass


def _call(token: str, method: str, payload: dict | None = None, timeout: float = 15) -> dict:
    url = f"{TELEGRAM_API}/bot{token}/{method}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            body = {}
        raise NotifyError(body.get("description") or f"Telegram returned {e.code}") from e
    except OSError as e:
        raise NotifyError(f"Could not reach Telegram: {e}") from e
    if not body.get("ok"):
        raise NotifyError(body.get("description", "Telegram refused the request"))
    return body


def valid_token(token: str) -> bool:
    return bool(TOKEN_RE.match(token.strip()))


def send(token: str, chat_id: str, text: str) -> None:
    _call(token, "sendMessage", {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True})


def find_chat(token: str) -> tuple[str, str] | None:
    """(chat_id, name) of the latest person who messaged the bot, or None."""
    updates = _call(token, "getUpdates").get("result", [])
    for update in reversed(updates):
        msg = update.get("message") or update.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if "id" in chat:
            name = chat.get("first_name") or chat.get("username") or chat.get("title") or ""
            return str(chat["id"]), name
    return None


def _order_text(task) -> str:
    if task.orders is None or task.orders.empty:
        return ""
    parts = []
    for o in task.orders.itertuples():
        qty = f"{o.shares:,.0f}" if float(o.shares).is_integer() else f"{o.shares:,.4f}"
        parts.append(f"{qty} {o.ticker}")
    return " → buy " + ", ".join(parts)


def reminder_text(tasks: list, today=None, app_url: str = "") -> str | None:
    """The Telegram message for a list of Action tasks; None when there's nothing to do."""
    if not tasks:
        return None
    today = pd.Timestamp(today or pd.Timestamp.today())
    now = [t for t in tasks if t.priority < 2]
    later = [t for t in tasks if t.priority >= 2]
    lines = [f"🔔 InvestTrack, {today:%a %b %d}"]
    if now:
        lines.append(f"{len(now)} thing(s) to do:")
        for t in now:
            section = BUCKETS[t.bucket].icon + " " if t.bucket in BUCKETS else ""
            lines.append(f"{section}{TASK_ICONS.get(t.kind, '•')} {t.title}{_order_text(t)}")
    if later:
        lines.append("Optional: " + "; ".join(t.title for t in later))
    lines.append("After doing them, press Done in the Action tab" + (f": {app_url}" if app_url else "."))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send InvestTrack reminders to Telegram.")
    parser.add_argument("--test", action="store_true", help="send a test message")
    parser.add_argument("--dry-run", action="store_true", help="print the message, don't send it")
    args = parser.parse_args(argv)

    from .actions import build_tasks
    from .data import fetch_prices
    from .report import history_period
    from .storage import make_store

    state, _ = make_store().load()
    if not state.telegram_ready and not args.dry_run:
        print("Telegram is not set up yet: open the app, Settings → Notifications.")
        return 0
    if args.test:
        send(state.telegram["token"], state.telegram["chat_id"], "✅ InvestTrack reminders are working.")
        print("Test message sent.")
        return 0
    tickers = sorted(set(state.all_tickers()) | set(state.market_overview))
    prices = fetch_prices(tickers, history_period(state))
    if prices.empty:
        print("Could not download prices; no reminder sent.")
        return 1
    text = reminder_text(build_tasks(state, prices), app_url=state.app_url)
    if text is None:
        print("Nothing to do today; no reminder sent.")
        return 0
    if args.dry_run:
        print(text)
        return 0
    send(state.telegram["token"], state.telegram["chat_id"], text)
    print("Reminder sent:\n" + text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

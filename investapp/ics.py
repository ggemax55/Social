"""Calendar file (.ics) with a reminder for every plan's schedule.

Open the file on an iPhone (or import it into Google/Outlook calendar) and your
phone reminds you on each contribution day, even when the app is closed.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from .buckets import BUCKETS
from .money import fmt
from .planner import Plan

_DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _rule(plan: Plan) -> str:
    start = pd.Timestamp(plan.start_date)
    if plan.frequency == "daily":
        return "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
    if plan.frequency == "weekly":
        return f"FREQ=WEEKLY;BYDAY={_DAYS[start.weekday()]}"
    if plan.frequency == "monthly":
        return f"FREQ=MONTHLY;BYMONTHDAY={start.day if start.day <= 28 else -1}"
    return f"FREQ=YEARLY;BYMONTH={start.month};BYMONTHDAY={min(start.day, 28)}"


def plans_calendar(plans: list[Plan], app_url: str = "", hour: int = 9) -> str:
    """iCalendar text: one repeating all-day event per active plan, with an alert at `hour`:00."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//InvestTrack//Reminders//EN", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:InvestTrack"]
    for p in plans:
        if not p.active:
            continue
        section = BUCKETS[p.bucket].label if p.bucket in BUCKETS else ""
        summary = f"InvestTrack: {p.name} ({fmt(p.amount, p.currency)})"
        description = (f"{section}. Open InvestTrack → Action to see exactly what to buy, then press Done."
                       + (f"\n{app_url}" if app_url else ""))
        start = pd.Timestamp(p.start_date)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{p.id}@investtrack",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
            f"RRULE:{_rule(p)}",
            f"SUMMARY:{_escape(summary)}",
            f"DESCRIPTION:{_escape(description)}",
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_escape(summary)}",
            f"TRIGGER:PT{hour}H",
            "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"

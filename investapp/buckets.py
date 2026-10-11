"""The three sections of your money, by how soon you may need it.

- short:  "daily bread"     money you may need within about a year: safe, easy to sell
- income: "monthly income"  money for the next few years that pays you regularly
- long:   "long term"       money you won't touch for 5+ years: grows the most, swings the most

These are time horizons, not schedules: any section can receive money daily, weekly or monthly.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Bucket:
    key: str
    name: str
    icon: str
    horizon: str
    purpose: str
    default_mix: dict[str, float] = field(default_factory=dict)
    why: str = ""

    @property
    def label(self) -> str:
        return f"{self.icon} {self.name}"


BUCKETS: dict[str, Bucket] = {
    "short": Bucket(
        "short", "Short term: daily bread", "🍞", "within about a year",
        "Money you may need soon. Safety first: it should not drop much and you can sell it any day.",
        {"SGOV": 100},
        "SGOV holds US Treasury bills that mature within 3 months: very low risk, pays interest every month. "
        "If you'll spend this money in drams, an AMD bank deposit also works and avoids exchange-rate risk.",
    ),
    "income": Bucket(
        "income", "Medium term: monthly income", "💵", "about 1 to 5 years",
        "Money that pays you regularly while it grows a little. Moderate ups and downs.",
        {"BND": 50, "SCHD": 50},
        "BND (US bonds) pays interest every month; SCHD (large US companies that pay dividends) pays every "
        "quarter. You can take the payouts as income or reinvest them.",
    ),
    "long": Bucket(
        "long", "Long term: growth", "🌳", "5 years or more",
        "Money you won't touch for years. Grows the most over time, but can fall 30-50% along the way.",
        {"VT": 100},
        "VT owns about 9,000 companies in almost every country: the simplest way to own the world's "
        "stock market in one purchase.",
    ),
}
BUCKET_KEYS = tuple(BUCKETS)
DEFAULT_SPLIT = {"short": 20, "income": 30, "long": 50}

# Plans made before sections existed were named by schedule.
_FROM_FREQUENCY = {"daily": "short", "weekly": "income", "monthly": "long", "yearly": "long"}


def bucket_for_frequency(frequency: str) -> str:
    return _FROM_FREQUENCY.get(frequency, "long")


def label(key: str) -> str:
    b = BUCKETS.get(key)
    return b.label if b else "📦 Not in a section"


def normalize_split(split: dict[str, float]) -> dict[str, float]:
    """Section weights as fractions summing to 1 (missing sections count as 0)."""
    clean = {k: max(0.0, float(split.get(k, 0) or 0)) for k in BUCKET_KEYS}
    total = sum(clean.values())
    return {k: v / total for k, v in clean.items()} if total > 0 else {k: 0.0 for k in BUCKET_KEYS}

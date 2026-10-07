"""Broker profiles: what each purchase costs, and how big a purchase must be to keep fees low."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

NOT_CHOSEN = "Not chosen yet"
GOOD_FEE_SHARE = 0.005  # fees of at most 0.5% of a purchase are good
MAX_FEE_SHARE = 0.01  # above 1%, plans save up before buying


@dataclass
class Broker:
    """Fees in USD per order: the largest of `min_fee`, `per_share` x shares and
    `pct` x order value, capped at `max_pct` x order value when `max_pct` > 0."""

    name: str = NOT_CHOSEN
    per_share: float = 0.0
    pct: float = 0.0
    min_fee: float = 0.0
    max_pct: float = 0.0
    fractional: bool = True
    note: str = ""

    def order_fee(self, amount: float, price: float) -> float:
        if amount <= 0:
            return 0.0
        shares = amount / price if price and price > 0 else 0.0
        fee = max(self.min_fee, self.per_share * shares, self.pct * amount)
        if self.max_pct > 0:
            fee = min(fee, self.max_pct * amount)
        return fee

    def fee_share(self, amount: float, price: float = 100.0) -> float:
        return self.order_fee(amount, price) / amount if amount > 0 else math.nan

    def min_good_order(self, max_share: float = GOOD_FEE_SHARE, price: float = 100.0) -> float:
        """Smallest order (USD) whose fee is at most `max_share` of the order; inf if none."""
        def ok(amount: float) -> bool:
            return self.fee_share(amount, price) <= max_share + 1e-12

        if not ok(1e7):
            return math.inf
        if ok(1.0):
            return 0.0
        lo, hi = 1.0, 1e7
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (lo, mid) if ok(mid) else (mid, hi)
        return float(math.ceil(hi - 1e-6))

    @property
    def chosen(self) -> bool:
        return self.name != NOT_CHOSEN

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Broker":
        d = d or {}
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


# Published fees for US stocks/ETFs as found in 2026. Always confirm on the broker's own site.
BROKER_PRESETS: dict[str, Broker] = {
    NOT_CHOSEN: Broker(),
    "Interactive Brokers (direct account)": Broker(
        "Interactive Brokers (direct account)", per_share=0.0035, min_fee=0.35, max_pct=0.01, fractional=True,
        note="IBKR Pro tiered: $0.0035/share, min $0.35, max 1% per order, plus small exchange fees. "
        "Offers fractional shares. interactivebrokers.com",
    ),
    "Interactive Brokers via Acba bank": Broker(
        "Interactive Brokers via Acba bank", per_share=0.01, min_fee=4.0, fractional=False,
        note="Acba's published US-market fee: $0.01/share, min $4 per order. Ask Acba whether fractional "
        "shares are available. acba.am",
    ),
    "Freedom Broker Armenia": Broker(
        "Freedom Broker Armenia", pct=0.0012, min_fee=1.20, fractional=False,
        note="Standard tariff: 0.12% per order, min $1.20, no monthly fee. Ask whether fractional shares "
        "are available. ffin.am",
    ),
    "Other broker (enter fees)": Broker("Other broker (enter fees)"),
}

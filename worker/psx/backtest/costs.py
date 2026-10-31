"""PSX trading cost model. All rates are configurable; verify current rates with your broker, FBR and PSX."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class CostModel:
    brokerage_pct: float = 0.15          # % of trade value per side
    brokerage_min_per_share: float = 0.03  # Rs per share minimum brokerage
    sales_tax_on_brokerage_pct: float = 13.0
    cdc_per_share: float = 0.005         # CDC charges, Rs per share per side
    nccpl_secp_per_share: float = 0.005  # NCCPL / SECP / regulatory, Rs per share per side
    slippage_pct: float = 0.10           # % adverse price move per side
    cgt_pct: float = 15.0                # capital gains tax on net realised gains per tax year (filer)

    @classmethod
    def from_dict(cls, d: dict | None) -> "CostModel":
        d = d or {}
        return cls(**{k: float(v) for k, v in d.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        return asdict(self)

    def fill_price(self, price: float, side: str) -> float:
        s = self.slippage_pct / 100
        return price * (1 + s) if side == "buy" else price * (1 - s)

    def side_costs(self, price: float, shares: int) -> dict:
        value = price * shares
        brokerage = max(value * self.brokerage_pct / 100, shares * self.brokerage_min_per_share)
        sst = brokerage * self.sales_tax_on_brokerage_pct / 100
        fees = shares * (self.cdc_per_share + self.nccpl_secp_per_share)
        return {"brokerage": brokerage, "sales_tax": sst, "fees": fees, "total": brokerage + sst + fees}

    def round_trip(self, entry: float, exit_: float, shares: int) -> dict:
        b, s = self.side_costs(entry, shares), self.side_costs(exit_, shares)
        gross = (exit_ - entry) * shares
        costs = b["total"] + s["total"]
        return {"gross": gross, "buy_costs": b, "sell_costs": s, "costs": costs, "net_before_tax": gross - costs}


def cgt_by_tax_year(trades: list[dict], cgt_pct: float) -> dict:
    """Pakistan tax year runs July-June. CGT on positive net realised gains per tax year."""
    years: dict[str, float] = {}
    for t in trades:
        if t.get("status") != "closed" or not t.get("exit_date"):
            continue
        d = str(t["exit_date"])
        y, m = int(d[:4]), int(d[5:7])
        ty = f"TY{y + 1 if m >= 7 else y}"
        years[ty] = years.get(ty, 0.0) + t["net_pnl"]
    tax = {ty: max(0.0, g) * cgt_pct / 100 for ty, g in years.items()}
    return {"by_year": {ty: {"net_gain": years[ty], "cgt": tax[ty]} for ty in sorted(years)}, "total": sum(tax.values())}

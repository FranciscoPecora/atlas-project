# %% [markdown]
# # Ledger against VIINA (external validity)
#
# Spearman correlation of daily event counts by oblast between the ledger and VIINA
# 2.0 (Zhukov and Ayers, Open Database License), over the oblast-days the collected
# reports cover (SPEC 5.3, no target). The numbers come from `src/viina.py`; this
# file only displays them and writes nothing. Run it as a script or cell by cell.

# %%
import polars as pl

from src.config import load_config
from src.gazetteer import read_table
from src.link import LEDGER
from src.viina import (
    compare,
    covered_days,
    daily_counts,
    fetch,
    ledger_events,
    oblast_day_grid,
    read_viina,
)

cfg = load_config()
ledger = pl.read_parquet(LEDGER)
vi = read_viina(fetch(cfg), cfg["viina"]["oblast_names"])
oblast_of = {p.gazetteer_id: p.oblast for p in read_table() if p.oblast}
days = covered_days(
    ledger["report_date"].cast(pl.String).unique().to_list(),
    str(cfg["corpus"]["start"]),
    str(cfg["corpus"]["end"]),
)
print(f"{len(days)} covered days, {days[0]} to {days[-1]}")

# %%
res = compare(ledger, vi, oblast_of, days)
for label in ("t_mil", "all"):
    print(label, res[label])

# %% [markdown]
# ## Totals by oblast
# Where the two sources put their events, summed over the covered days.

# %%
ours = daily_counts(ledger_events(ledger, oblast_of), days)
theirs = daily_counts(vi.filter("t_mil"), days)
grid = oblast_day_grid(ours, theirs, days)
print(
    grid.group_by("oblast")
    .agg(pl.col("n_a").sum().alias("ledger"), pl.col("n_b").sum().alias("viina_t_mil"))
    .sort("ledger", descending=True)
)

# %% [markdown]
# ## Per-oblast correlation over days
# Front oblasts only (at least 10 ledger events); a large share of the pooled
# correlation can come from which oblasts are active at all, not from day-to-day
# agreement. This view separates the two.

# %%
for (oblast,), g in grid.group_by("oblast"):
    if g["n_a"].sum() >= 10:
        rho = g.select(pl.corr("n_a", "n_b", method="spearman")).item()
        print(f"{oblast:20s} rho over days = {rho}")

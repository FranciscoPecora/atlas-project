# %% [markdown]
# # Claimed versus confirmed (H2)
#
# How often Russian-claimed territorial advances in the first 90 days are later
# confirmed by geolocation, within 7, 14 and 30 report days, and the median lag per
# sector (SPEC 5.2 rule 7b, SPEC 5.3 H2). Intervals: percentile bootstrap over the
# claims' reports, 2,000 resamples, seed 20261116.
#
# The numbers come from `src/h2.py`; this file only displays them. Run it as a
# script (`uv run python notebooks/01_claimed_vs_confirmed.py`) or cell by cell in
# an editor that reads `# %%` cells. It reads data/ledger.parquet and writes nothing.

# %%
import polars as pl

from src.config import load_config
from src.h2 import compute, describe
from src.link import LEDGER, confirmation_links

cfg = load_config()
ledger = pl.read_parquet(LEDGER)
print(ledger.group_by("source", "epistemic_status").len().sort("len", descending=True))

# %% [markdown]
# ## Rule 7b candidates
# Territorial advances by status and precision, before the H2 filter.

# %%
advances = ledger.filter(pl.col("event_type") == "territorial_advance")
print(advances.group_by("epistemic_status", "geo_precision").len().sort("len", descending=True))

# %%
links, excluded = confirmation_links(
    ledger,
    str(cfg["corpus"]["start"]),
    str(cfg["corpus"]["analysis_end"]),
    cfg["link"]["confirmation_days"],
)
print(f"{links.height} eligible claims; {excluded} excluded for geo_precision > 1")
print(links.head(20))

# %% [markdown]
# ## H2

# %%
res, excluded = compute(ledger, cfg)
print(describe(res, excluded))

# %% [markdown]
# ## Lag distribution of confirmed claims

# %%
confirmed = links.filter(pl.col("lag_days").is_not_null())
if confirmed.height:
    print(confirmed.group_by("lag_days").len().sort("lag_days"))
else:
    print("No confirmed claim.")

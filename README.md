# Claimline

Turns daily war reporting into a queryable ledger of events in which every record keeps who claimed it, the exact words it rests on (as character offsets, not text), and whether it was later confirmed.

**Status: milestone 1 (spec, guideline, collector).** No results yet. Metric definitions and targets were frozen in [SPEC.md](SPEC.md) before any pipeline code.

## Question

How often are battlefield claims later confirmed, and how fast? See [SPEC.md](SPEC.md) for hypotheses H1 and H2 and every metric definition.

## Sources

- Ukrainian General Staff 08:00 operational updates, republished by [ArmyInform](https://armyinform.com.ua) under CC BY 4.0.
- ISW Russian Offensive Campaign Assessments: pending written permission. See [docs/permissions.md](docs/permissions.md). Source: Institute for the Study of War.

Source text is stored locally and never committed or published.

## Limits

This measures confirmation inside the sources' own reporting, not ground truth. There is one annotator; agreement figures measure self-consistency only. The annotator reads no Ukrainian: General Staff dev reports were labelled with a Claude translation shown beside the original, which may bias those labels toward Claude's reading. General Staff dev labels are machine-made: rule-based pre-fills, revised by a reviewer model (a larger Claude model than the extractor), then spot-checked by the annotator on a random sample of 30 events and 10 paragraphs read in translation. They are not a human key: the reviewer and the evaluated systems are models of one family, so shared mistakes can raise measured scores, and the spot check cannot catch translation errors. SPEC amendment A1 (docs/spec_amendment_A1.md) allows the General Staff test labels to be made the same way, once, before any evaluated system runs on those reports.

## Intended use

Research on the reliability of open-source battlefield reporting. Not for operational targeting. Anything shown on a map is delayed by 48 hours.

## Reproduce

```bash
uv sync
uv run pytest -q
uv run python -m src.collect --source gsu --dates 2026-07-21,2026-07-29,2026-08-06
uv run python -m src.segment data/text/gsu/*.txt
```

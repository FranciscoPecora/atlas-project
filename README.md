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

This measures confirmation inside the sources' own reporting, not ground truth. There is one annotator; agreement figures measure self-consistency only. The annotator reads no Ukrainian: General Staff dev reports were labelled with a Claude translation shown beside the original, which may bias those labels toward Claude's reading. General Staff dev labels are machine-made: rule-based pre-fills, revised by a reviewer model (a larger Claude model than the extractor), then spot-checked by the annotator on a random sample of 30 events and 10 paragraphs read in translation. They are not a human key: the reviewer and the evaluated systems are models of one family, so shared mistakes can raise measured scores, and the spot check cannot catch translation errors. On the dev key the spot check found 1 of 30 sampled events wrong (3.3%, 95% interval 0.6% to 16.7%) and 0 of 9 judged paragraphs incomplete (interval 0% to 29.9%); the sample is small, so the intervals are wide. The General Staff test key (12 reports, 621 events) was made once on 2026-11-17 and locked in commit 9da84a1, before any evaluated system ran on those reports; its spot check found 1 of 28 judged events wrong (3.6%, 95% interval 0.6% to 17.7%) and 0 of 9 judged paragraphs incomplete, after the annotator re-read three items he had first marked wrong under an instruction the page had left out (as first answered: 3 of 28, 10.7%, above the 5% limit). Reviewer stability on two dev reports: 125 of 125 events matched between two runs, kappa 1.0 on type and status. SPEC amendment A1 (docs/spec_amendment_A1.md) allows the General Staff test labels to be made the same way, once, before any evaluated system runs on those reports.

## Results so far

Dev split only: 3 General Staff reports, 181 gold events (2026-11-18). Event F1 as in SPEC.md 5.1 at 10 km and 1 day; intervals resample whole reports.

| System | Precision | Recall | F1 | 95% interval |
| --- | --- | --- | --- | --- |
| B0, rules and gazetteer | 1.000 | 0.950 | 0.975 | 0.946 to 1.000 |
| B1, GLiNER2 and rules | 0.958 | 0.890 | 0.923 | 0.889 to 0.955 |

B0's score is circular: the General Staff key started from the same rules. General Staff reports follow one sentence pattern, so both baselines already pass the 0.80 target; hypothesis H1 cannot be answered on these reports alone and needs the ISW reports. No ISW report is collected yet (permission pending). 108 of the 120 General Staff days are collected; the other 12 have no post that states the 08:00 cutoff. Test-split scores are not computed until the release.

## Intended use

Research on the reliability of open-source battlefield reporting. Not for operational targeting. Anything shown on a map is delayed by 48 hours.

## Reproduce

```bash
uv sync
uv run pytest -q
uv run python -m src.collect --source gsu --dates 2026-07-21,2026-07-29,2026-08-06
uv run python -m src.segment data/text/gsu/*.txt
```

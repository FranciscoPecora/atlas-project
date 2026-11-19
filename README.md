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

This measures confirmation inside the sources' own reporting, not ground truth. There is one annotator; agreement figures measure self-consistency only. The annotator reads no Ukrainian: General Staff dev reports were labelled with a Claude translation shown beside the original, which may bias those labels toward Claude's reading. General Staff dev labels are machine-made: rule-based pre-fills, revised by a reviewer model (a larger Claude model than the extractor), then spot-checked by the annotator on a random sample of 30 events and 10 paragraphs read in translation. They are not a human key: the reviewer and the evaluated systems are models of one family, so shared mistakes can raise measured scores, and the spot check cannot catch translation errors. On the dev key the spot check found 1 of 30 sampled events wrong (3.3%, 95% interval 0.6% to 16.7%) and 0 of 9 judged paragraphs incomplete (interval 0% to 29.9%). A second, larger sample with no item in common found 1 of 100 events wrong and 0 of 20 paragraphs incomplete; together, 2 of 130 events wrong (1.5%, 95% interval 0.4% to 5.4%) and 0 of 29 paragraphs incomplete (interval 0% to 11.7%). Both samples were drawn before hard case 13 changed two paragraphs of the key. The one event marked wrong in the second sample is a shelling count that the English reading aid rendered as "attacks with fire": the audit can fail a correct event, or pass a wrong one, because of the translation. The General Staff test key (12 reports, 621 events) was made once on 2026-11-17 and locked in commit 9da84a1, before any evaluated system ran on those reports; its spot check found 1 of 28 judged events wrong (3.6%, 95% interval 0.6% to 17.7%) and 0 of 9 judged paragraphs incomplete, after the annotator re-read three items he had first marked wrong under an instruction the page had left out (as first answered: 3 of 28, 10.7%, above the 5% limit). The annotator also labelled the three dev reports by hand from the translation, without seeing the key (51 paragraphs, 30 minutes): 171 of his 177 events and of the key's 175 pair up (F1 0.972), with the same type on 170 pairs (kappa 0.915); all 163 events at named villages are in both. The differences are in headline and total paragraphs, where he departed from the guideline five times. The pass also showed that the key wrote two-direction paragraphs in two different ways, which was then fixed in the dev key (hard case 13). He asked about five paragraphs while labelling, so this pass is not fully independent. Reviewer stability on two dev reports: 125 of 125 events matched between two runs, kappa 1.0 on type and status. SPEC amendment A1 (docs/spec_amendment_A1.md) allows the General Staff test labels to be made the same way, once, before any evaluated system runs on those reports.

## Results so far

Dev split only: 3 General Staff reports, 175 gold events (2026-11-18, after hard case 13 was applied to the key; see below). Event F1 as in SPEC.md 5.1 at 10 km and 1 day; intervals resample whole reports. "Held-out" leaves out the report of 21 July, whose paragraphs are the worked examples in the extraction prompt (2 reports, 119 events).

| System | Precision | Recall | F1 | 95% interval | Held-out F1 |
| --- | --- | --- | --- | --- | --- |
| B0, rules and gazetteer | 1.000 | 0.983 | 0.991 | 0.972 to 1.000 | 1.000 |
| B1, GLiNER2 and rules | 0.958 | 0.920 | 0.939 | 0.914 to 0.955 | 0.950 |
| B2, one free-form prompt | 1.000 | 0.989 | 0.994 | 0.981 to 1.000 | 0.992 |
| S1, schema-constrained extraction | 0.983 | 0.983 | 0.983 | 0.946 to 1.000 | 1.000 |
| S2, S1 plus deterministic verification | 0.983 | 0.971 | 0.977 | 0.946 to 1.000 | 0.992 |

B2, S1 and S2 use `claude-haiku-5-5` at effort low. S1 at effort medium scores 0.997 (held-out 0.996, against 1.000 for low). Each system was run once, so differences of this size are within run-to-run variation; low stays.

What the table does and does not show:

- **No system is separated from another.** All intervals overlap, and three reports are too few to rank them. The schema (S1) does not beat the free-form prompt (B2) on these reports.
- **Verification cost recall here and bought no precision.** S2 rejected 2 of S1's 175 events, both because the place is not inside the quote, and both were correct events. Recall fell from 0.983 to 0.971.
- **S1's 3 misses and 3 false alarms are one sentence:** "the enemy showed activity in the areas of" three villages, which the key writes as three ground assaults and S1 as three events of type `other`. It is in the report whose other paragraphs are the prompt's worked examples.
- **These numbers replace an earlier run on the same day** (key of 181 events: S1 0.981, B2 0.983, quantity exact match 0.625 and 0.333). The key wrote paragraphs that open with two directions in two different ways; the annotator's hand pass exposed it, hard case 13 of the guideline now rules on it, two paragraphs of the dev key were rewritten (src/keyfix.py) and the three model systems were run again with the new rule. The earlier rows stay in eval/results.csv. The test key was made by the same reviewer before this rule existed and is locked, so it may hold the same inconsistency.
- **Quantity exact match is 1.000** for B0 (11 matched events with a number), B2 (14) and S1 (14), target 0.95. The earlier shortfall came from the key's inconsistency, not from the systems. B1 is 0.0 on 2.
- **Epistemic status accuracy is 1.000 for every system**, which says little: every General Staff event is `ua_claimed`.
- **Cost and speed, measured from API usage:** S1 costs 0.0081 USD (0.0073 EUR) per report, B2 0.0072 USD; target below 0.10 EUR. Median time per report is 42.9 s for S1 and 41.0 s for B2; target below 60 s (the earlier run measured 57.8 s for S1, so the margin varies).

Limits that apply to every number above. The General Staff key is machine-made and audited by sample (SPEC amendment A1). The extractor and the key's reviewer are models of one family reading the same guideline, so agreement is easier than with a human key. B0 is circular: the key started from the same rules. General Staff reports follow one sentence pattern, so every system already passes the 0.80 target and hypothesis H1 (S3 beats B2 by 0.08) cannot be shown on these reports; it needs the ISW reports. No ISW report is collected yet (permission pending). 108 of the 120 General Staff days are collected; the other 12 have no post that states the 08:00 cutoff. Test-split scores are not computed until the release.

## Intended use

Research on the reliability of open-source battlefield reporting. Not for operational targeting. Anything shown on a map is delayed by 48 hours.

## Reproduce

```bash
uv sync
uv run pytest -q
uv run python -m src.collect --source gsu --dates 2026-07-21,2026-07-29,2026-08-06
uv run python -m src.segment data/text/gsu/*.txt
```

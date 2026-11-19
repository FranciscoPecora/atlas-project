# Claimline

Turns daily war reporting into a queryable ledger of events in which every record keeps who claimed it, the exact words it rests on (as character offsets, not text), and whether it was later confirmed.

**Status: milestone 5 (test split scored once, 2026-11-19).** Metric definitions and targets were frozen in [SPEC.md](SPEC.md) before any pipeline code. General Staff reports only: ISW permission is still pending.

## Question

How often are battlefield claims later confirmed, and how fast? See [SPEC.md](SPEC.md) for hypotheses H1 and H2 and every metric definition.

## Sources

- Ukrainian General Staff 08:00 operational updates, republished by [ArmyInform](https://armyinform.com.ua) under CC BY 4.0.
- ISW Russian Offensive Campaign Assessments: pending written permission. See [docs/permissions.md](docs/permissions.md). Source: Institute for the Study of War.

Source text is stored locally and never committed or published.

## Limits

This measures confirmation inside the sources' own reporting, not ground truth. There is one annotator; agreement figures measure self-consistency only. The annotator reads no Ukrainian: General Staff dev reports were labelled with a Claude translation shown beside the original, which may bias those labels toward Claude's reading. General Staff dev labels are machine-made: rule-based pre-fills, revised by a reviewer model (a larger Claude model than the extractor), then spot-checked by the annotator on a random sample of 30 events and 10 paragraphs read in translation. They are not a human key: the reviewer and the evaluated systems are models of one family, so shared mistakes can raise measured scores, and the spot check cannot catch translation errors. On the dev key the spot check found 1 of 30 sampled events wrong (3.3%, 95% interval 0.6% to 16.7%) and 0 of 9 judged paragraphs incomplete (interval 0% to 29.9%). A second, larger sample with no item in common found 1 of 100 events wrong and 0 of 20 paragraphs incomplete; together, 2 of 130 events wrong (1.5%, 95% interval 0.4% to 5.4%) and 0 of 29 paragraphs incomplete (interval 0% to 11.7%). Both samples were drawn before hard case 13 changed two paragraphs of the key. The one event marked wrong in the second sample is a shelling count that the English reading aid rendered as "attacks with fire": the audit can fail a correct event, or pass a wrong one, because of the translation. The General Staff test key (12 reports, 621 events) was made once on 2026-11-17 and locked in commit 9da84a1, before any evaluated system ran on those reports; its spot check found 1 of 28 judged events wrong (3.6%, 95% interval 0.6% to 17.7%) and 0 of 9 judged paragraphs incomplete, after the annotator re-read three items he had first marked wrong under an instruction the page had left out (as first answered: 3 of 28, 10.7%, above the 5% limit). The annotator also labelled the three dev reports by hand from the translation, without seeing the key (51 paragraphs, 30 minutes): 171 of his 177 events and of the key's 175 pair up (F1 0.972), with the same type on 170 pairs (kappa 0.915); all 163 events at named villages are in both. The differences are in headline and total paragraphs, where he departed from the guideline five times. The pass also showed that the key wrote two-direction paragraphs in two different ways, which was then fixed in the dev key (hard case 13). He asked about five paragraphs while labelling, so this pass is not fully independent. Reviewer stability on two dev reports: 125 of 125 events matched between two runs, kappa 1.0 on type and status. SPEC amendment A1 (docs/spec_amendment_A1.md) allows the General Staff test labels to be made the same way, once, before any evaluated system runs on those reports.

## Release results (test split, scored once)

`make eval-test` ran once on 2026-11-19 at commit 280376d (config 3e5cc21ab07a; [eval/test_run.json](eval/test_run.json)): 12 General Staff test reports, 621 key events, none of them seen while building. Event F1 as in SPEC 5.1 at 10 km and 1 day; 95% intervals resample whole reports (2,000 resamples, seed 20261116). Model systems ran through the Message Batches API.

| System | Precision | Recall | F1 | 95% interval | Quantity exact (n) | USD per report |
| --- | --- | --- | --- | --- | --- | --- |
| B0, rules and gazetteer | 0.998 | 0.765 | 0.866 | 0.800 to 0.929 | 0.944 (18) | 0 |
| B1, GLiNER2 and rules | 0.961 | 0.836 | 0.894 | 0.849 to 0.926 | 0.000 (19) | 0 |
| B2, one free-form prompt | 0.991 | 0.934 | **0.962** | 0.951 to 0.973 | 0.958 (24) | 0.0030 |
| S1, schema-constrained extraction | 0.985 | 0.929 | 0.956 | 0.944 to 0.969 | 0.964 (28) | 0.0034 |
| S2, S1 plus deterministic verification | 0.990 | 0.915 | 0.951 | 0.932 to 0.968 | 0.963 (27) | 0.0034 |
| S3-H, S2 plus Haiku verifier and geocoder (shipped) | 0.939 | 0.847 | 0.891 | 0.869 to 0.917 | 0.960 (25) | 0.0156 |
| S3-S, S2 plus Sonnet verifier and geocoder | 0.944 | 0.834 | 0.885 | 0.861 to 0.914 | 0.960 (25) | 0.0461 |

Cost is batch price (half the live price). Epistemic status accuracy is 1.000 for every system and says nothing here: every General Staff event is `ua_claimed`.

**F1 sensitivity (SPEC 5.3), K km x D days.** Almost flat: the day window changes nothing, and widening to 25 km adds 0.002 for B1 and 0.015 to 0.018 for the two S3 variants, whose previous-day geocoding rule puts some events 10 to 25 km from where the key's rules put them:

| System | 5 km, 0 to 2 d | 10 km, 0 to 2 d | 25 km, 0 to 2 d |
| --- | --- | --- | --- |
| B0 | 0.866 | 0.866 | 0.866 |
| B1 | 0.894 | 0.894 | 0.896 |
| B2 | 0.962 | 0.962 | 0.962 |
| S1 | 0.956 | 0.956 | 0.956 |
| S2 | 0.951 | 0.951 | 0.951 |
| S3-H | 0.889 | 0.891 | 0.906 |
| S3-S | 0.884 | 0.885 | 0.903 |

Within each K the three day settings give the same F1 to three decimals.

**H1, not supported.** S3-H event F1 is 0.891 (0.869 to 0.917), above the 0.80 target, but S3-H minus B2 is -0.071, not +0.08: B2 scores 0.962 (0.951 to 0.973), and the two intervals do not overlap. Each verification layer cost recall and bought little precision on these reports: S2 rejected 12 of S1's 586 events, and the S3 verifier and geocoder took F1 from 0.951 to 0.891. General Staff reports follow one sentence pattern that a single free-form prompt already handles; whether the layers pay off on varied text (ISW) is untested.

**H2, unanswered.** Rule 7b found 0 eligible claims in the 120-day ledger, so the confirmed shares at 7, 14 and 30 days and the median lag are undefined. The ledger holds 4,550 events from 108 reports and every one is `ua_claimed`: the General Staff does not report Russian claims or geolocated confirmations. H2 needs the ISW reports.

**The ledger.** 4,550 events, 4,448 located; rule 7a puts 3,852 of them in 436 duplicate clusters of two or more. The widest cluster is 22.5 km across and the longest spans 82 days: a village named in most daily reports chains into one cluster (single linkage, SPEC 5.2). Against VIINA 2.0, daily event counts by oblast correlate at Spearman 0.391 over 2,889 oblast-days (military-operations events; 0.337 for all VIINA events). Most of that comes from which oblasts are active at all: within Donetsk oblast, day to day, it is 0.37, and between -0.19 and 0.11 in the other front oblasts.

**Targets missed or not measured** (SPEC 5.3):

- **H1, S3 minus B2 >= 0.08:** missed, -0.071 (above).
- **H2:** not answerable on General Staff text (above).
- **Speed below 60 s per report:** missed on live calls, S3-H median 112 s on dev, because the verifier calls the API once per quote in sequence. The test run used batches and has no timing.
- **Geocoding accuracy@10 km >= 0.90:** not measured. On dev every located key event is precision 2 (n = 0); the scorer does not compute it on test, and the test key is not opened outside the scorer. A hand check of 50 dev places found 0.828 within 10 km.
- **Unsupported-field rate below 2%:** met on the point estimate only, S3-H 1.43% (95% interval 0.00% to 3.68%), dev-period audit.
- **Quantity exact match >= 0.95:** met by every model system (0.958 to 0.964), missed by the baselines B0 (0.944) and B1 (0.000).

Met: event F1 >= 0.80 for every system; cost below 0.10 EUR per report (S3-H 0.014 EUR at batch price, 0.016 EUR live); reviewer stability kappa 1.0 (SPEC amendment A1). The five worst error patterns are in [FAILURES.md](FAILURES.md).

Test-split limits: the General Staff test key is machine-made (amendment A1) and was made before hard case 13, so it may write two-direction paragraphs inconsistently; B0 shares the key's pre-fill rules; scores on these reports are high for every system, and the release says nothing yet about ISW text.

## Dev results

Dev split only: 3 General Staff reports, 175 gold events (2026-11-18, after hard case 13 was applied to the key; see below). Event F1 as in SPEC.md 5.1 at 10 km and 1 day; intervals resample whole reports. "Held-out" leaves out the report of 21 July, whose paragraphs are the worked examples in the extraction prompt (2 reports, 119 events).

| System | Precision | Recall | F1 | 95% interval | Held-out F1 |
| --- | --- | --- | --- | --- | --- |
| B0, rules and gazetteer | 1.000 | 0.983 | 0.991 | 0.972 to 1.000 | 1.000 |
| B1, GLiNER2 and rules | 0.958 | 0.920 | 0.939 | 0.914 to 0.955 | 0.950 |
| B2, one free-form prompt | 1.000 | 0.989 | 0.994 | 0.981 to 1.000 | 0.992 |
| S1, schema-constrained extraction | 0.983 | 0.983 | 0.983 | 0.946 to 1.000 | 1.000 |
| S2, S1 plus deterministic verification | 0.983 | 0.971 | 0.977 | 0.946 to 1.000 | 0.992 |
| S3-H, S2 plus Haiku field verifier and geocoder rules (shipped) | 0.930 | 0.914 | 0.922 | 0.904 to 0.937 | 0.915 |
| S3-S, S2 plus Sonnet field verifier and geocoder rules | 0.947 | 0.914 | 0.930 | 0.904 to 0.963 | 0.915 |

B2, S1 and S2 use `claude-haiku-5-5` at effort low. S1 at effort medium scores 0.997 (held-out 0.996, against 1.000 for low). Each system was run once, so differences of this size are within run-to-run variation; low stays.

What the table does and does not show:

- **No system is separated from another.** All intervals overlap, and three reports are too few to rank them. The schema (S1) does not beat the free-form prompt (B2) on these reports.
- **Verification cost recall here and bought no precision.** S2 rejected 2 of S1's 175 events, both because the place is not inside the quote (quote not in the text: 0; number not in the quote: 0), and both were correct events. Recall fell from 0.983 to 0.971.
- **S1's 3 misses and 3 false alarms are one sentence:** "the enemy showed activity in the areas of" three villages, which the key writes as three ground assaults and S1 as three events of type `other`. It is in the report whose other paragraphs are the prompt's worked examples.
- **These numbers replace an earlier run on the same day** (key of 181 events: S1 0.981, B2 0.983, quantity exact match 0.625 and 0.333). The key wrote paragraphs that open with two directions in two different ways; the annotator's hand pass exposed it, hard case 13 of the guideline now rules on it, two paragraphs of the dev key were rewritten (src/keyfix.py) and the three model systems were run again with the new rule. The earlier rows stay in eval/results.csv. The test key was made by the same reviewer before this rule existed and is locked, so it may hold the same inconsistency.
- **Quantity exact match is 1.000** for B0 (11 matched events with a number), B2 (14) and S1 (14), target 0.95. The earlier shortfall came from the key's inconsistency, not from the systems. B1 is 0.0 on 2.
- **Epistemic status accuracy is 1.000 for every system**, which says little: every General Staff event is `ua_claimed`.
- **Cost and speed, measured from API usage:** S1 costs 0.0081 USD (0.0073 EUR) per report, B2 0.0072 USD; target below 0.10 EUR. Median time per report is 42.9 s for S1 and 41.0 s for B2; target below 60 s (the earlier run measured 57.8 s for S1, so the margin varies).

Milestone 4 (model verifier, geocoder rules, 2026-11-19):

- **S3 scores lower than S2 on dev, and the drop is geocoding, not verification.** The verifiers dropped 1 (Haiku) and 4 (Sonnet) of 173 records. The geocoder's new previous-day rule moved 11 events to another village of the same name, and the key is placed by the rules without it, so each move counts as a miss whether or not it is right. On the places where the two disagree, the hand check below finds the previous-day rule right slightly more often (5 of 12 events against 4 of 12).
- **Unsupported-field rate (target below 2%)**, 200 records drawn from 20 dev-period General Staff reports that are not gold, every field judged by the annotator from a machine translation: S2 4.04% (95% interval 0.65% to 9.01%), S3-H 1.43% (0.00% to 3.68%), S3-S 1.68% (0.27% to 3.94%). S3-H meets the target on the point estimate only. Haiku ships, by SPEC section 6: Sonnet does not lower the rate by 1 point and costs six times as much.
- **The verifier's value is in dropping whole records, not in correcting fields.** It drops records whose quote is a bare list of places with no verb (Haiku dropped 11 of the 12 such records in the sample, plus 4 correct ones). Every field it set to null alone (25) was judged supported, and it kept 18 actor or target fields judged unsupported. The bare-list quotes are an extractor fault: on 9 August and 23 July most quotes lack the verb, so the verifiers dropped most records of those reports.
- **Geocoding accuracy@10 km (SPEC 5.3) is undefined on dev:** every located dev gold event is precision 2, so n = 0, and gold coordinates come from the same geocoder. In its place, a hand check of 50 random dev places: 0.828 of 58 events within 10 km of the place the annotator picked, median error 0 km. The annotator picked the namesake that lies among the other, uniquely named villages of the same paragraph, so this measures agreement with that clue, not ground truth. Every miss is a common name decided by a weak rule (nearest to the direction's town, or the previous day).
- **Cost and speed:** S3-H 0.018 USD (0.016 EUR) per report, S3-S 0.106 USD (0.097 EUR). Median 112 s and 91 s per report: both miss the 60 s target, because the verifier makes one call per quote in sequence.
- **Units:** the General Staff reports name no units, so the alias table is empty until ISW text is collected.
- The S3 rows in eval/results.csv carry commit 81f9780, but were produced with a scorer fix committed in ada8847 (S3 records lacked report fields); rerun at ada8847 or later to reproduce them.

Limits that apply to every number above. The General Staff key is machine-made and audited by sample (SPEC amendment A1). The extractor and the key's reviewer are models of one family reading the same guideline, so agreement is easier than with a human key. B0 is circular: the key started from the same rules. The key's coordinates come from the same geocoder rules as the systems', and in the hand check 10 of 58 located events (about 1 in 6) sit at the wrong namesake, all at names shared by several villages, for every system alike. General Staff reports follow one sentence pattern, so every system already passes the 0.80 target and hypothesis H1 (S3 beats B2 by 0.08) cannot be shown on these reports; it needs the ISW reports. No ISW report is collected yet (permission pending). 108 of the 120 General Staff days are collected; the other 12 have no post that states the 08:00 cutoff. Test-split scores are in the release section above.

## Intended use

Research on the reliability of open-source battlefield reporting. Not for operational targeting. Anything shown on a map is delayed by 48 hours.

## Reproduce

```bash
uv sync
uv run pytest -q
uv run python -m src.collect --source gsu --dates 2026-07-21,2026-07-29,2026-08-06
uv run python -m src.segment data/text/gsu/*.txt
```

# Claimline

Claimline turns daily war reports into a ledger of events. Each record keeps who made the claim, the exact passage it rests on (stored as character offsets, not text), and whether anyone later confirmed it.

**[Live map](https://franciscopecora.github.io/claimline/)** · [Public data](release/DATA_DICTIONARY.md) · [Failure analysis](FAILURES.md) · [Detailed results](docs/RESULTS.md) · [Pre-registered spec](SPEC.md)

## Result

I wrote the metrics and targets down before writing any pipeline code. I froze a held-out test set on 17 November 2026 (commit `9da84a1`) and scored it exactly once, on 19 November.

- **The ledger:** 4,550 events from 108 daily reports of the Ukrainian General Staff, 19 July to 15 November 2026. 4,448 of them are placed on the map.
- **Accuracy:** the shipped pipeline finds events with an F1 of **0.891** (95% interval 0.869 to 0.917) on 12 unseen reports. The target was 0.80.
- **The main hypothesis failed.** I expected verification layers to beat a single prompt by 0.08 F1. On this source they did the opposite: one free-form prompt scored **0.962**, and each added layer cost recall. The General Staff writes in one fixed sentence pattern, and a single prompt already handles it.
- **The confirmation question could not be asked yet.** The General Staff reports neither Russian claims nor independent geolocations, so there are no claim-and-confirmation pairs to measure. That part needs ISW reports, planned for version 2.
- **Cost:** 1.6 US cents per report for the shipped pipeline at batch price, against a target of 10 euro cents.

| System (test split, 12 reports, 621 events) | Precision | Recall | F1 (95% interval) | USD per report |
| --- | --- | --- | --- | --- |
| B0, rules and gazetteer | 0.998 | 0.765 | 0.866 (0.800 to 0.929) | 0 |
| B1, GLiNER2 and rules | 0.961 | 0.836 | 0.894 (0.849 to 0.926) | 0 |
| B2, one free-form prompt | 0.991 | 0.934 | **0.962** (0.951 to 0.973) | 0.0030 |
| S1, schema-constrained extraction | 0.985 | 0.929 | 0.956 (0.944 to 0.969) | 0.0034 |
| S2, S1 plus deterministic checks | 0.990 | 0.915 | 0.951 (0.932 to 0.968) | 0.0034 |
| S3-H, S2 plus model verifier and geocoder (shipped) | 0.939 | 0.847 | 0.891 (0.869 to 0.917) | 0.0156 |

An event counts as found when the type matches, the place is within 10 km and the date is within 1 day (SPEC 5.1). Intervals come from resampling whole reports.

## Why this matters

Open-source analysts read the same daily reports by hand and copy them into spreadsheets, and in that step the line between "Russia says", "Ukraine says" and "seen on video" tends to blur. Claimline keeps that line in every record (`epistemic_status`), and it points to the evidence by character offsets and a hash. Anyone can therefore check a record against the original without the dataset republishing the text.

## How it works

```
ArmyInform post ─► clean text ─► extract (Claude, schema output) ─► check the quote is in the text
      │                                                                    │
      └── SHA-256, URL                     model verifier drops unsupported fields
                                                                           │
             gazetteer (GeoNames + OSM) ─► coordinates ─► link duplicates ─► ledger
```

- **The model never writes offsets or coordinates.** The model copies a quote. Code finds that quote in the text and computes the offsets, and coordinates come only from the gazetteer. A record whose quote is not in the report is rejected.
- **Structured output.** Every model call returns a Pydantic schema, and the full corpus ran through the Message Batches API at half price.
- **Linking.** Rule 7a groups reports of the same event (same type, within 5 km and 3 days). Rule 7b pairs a claim with a later geolocated confirmation at the same place.

## What went wrong

The five worst error patterns are in [FAILURES.md](FAILURES.md). The largest:

1. **Wrong village with the same name.** About 1 in 6 places with a common name, such as Novoselivka, lands on the wrong village.
2. **Quotes cut down to a bare place name.** The verifier then cannot see the verb and drops the record.
3. **The model verifier removes fields that were correct.** Its value lies in dropping whole bad records, not in fixing fields.

Two targets were missed: speed (112 s per report on live calls, against a target of 60 s) and the H1 margin. Geocoding accuracy could not be measured on the test set. Details are in [docs/RESULTS.md](docs/RESULTS.md).

## Limits

- This measures what the reports claim, not what happened on the ground.
- The answer key for the General Staff reports was drafted by a model and audited by sample (2 of 130 sampled events wrong on dev, 1 of 28 on test; [SPEC amendment A1](docs/spec_amendment_A1.md)). The key and the systems are models from one family, so agreement comes easier than it would against a human key, and every score is likely somewhat high.
- There is one annotator, who does not read Ukrainian and worked from a machine translation.
- There is one source and one sentence pattern. Nothing here says how the pipeline does on ISW's varied English prose.

## Intended use

Research on the reliability of open-source battlefield reporting. It is not for targeting or operational use. The map leaves out anything dated within 48 hours of the build, and the data names no individuals.

## Data

[`release/ledger_public.parquet`](release/ledger_public.parquet) holds one row per event with a [JSON Schema](release/ledger_public.schema.json) and a [data dictionary](release/DATA_DICTIONARY.md). It contains no text from the reports: the evidence is given as offsets into the cleaned text, with that text's SHA-256 and the report URL. The release is built from a whitelist of fields, and a check refuses any Cyrillic string or any value copied from the reports.

Sources: Ukrainian General Staff operational updates republished by [ArmyInform](https://armyinform.com.ua) under CC BY 4.0; places from GeoNames (CC BY 4.0) and OpenStreetMap (ODbL). Source text stays local and is never committed.

## Reproduce

Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
make data
make all
```

- `make data` collects and cleans the reports (slow, network). Building the gazetteer needs GeoNames `UA.txt` in `data/raw/gazetteer/` (see `src/gazetteer.py`).
- `make all` runs lint, the tests (298), the dev-split scores and the site data.
- Without the private saved model runs, the scorer scores the two baselines and says which systems it skipped.
- `make fresh-clone` repeats `make all` in a clean clone that holds only the dev reports and the gazetteer.
- The paid steps are `make ledger` (the full corpus through the Batches API, about 1.7 USD) and `make eval-test`, which refuses to run a second time.

## Status

Version 1 was released on 19 November 2026 and covers the General Staff only. Version 2 will add ISW's daily assessments, if ISW grants permission, to answer the confirmation question (H2): how often, and how fast, Russian claims of advances are later geolocated.

Built by Francisco Pecora with Claude Code. Decisions and their reasons are logged in [DECISIONS.md](DECISIONS.md).

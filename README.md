# Atlas

Atlas turns daily war reports into a ledger of events. Each record keeps who made the claim, the exact passage it rests on (stored as character offsets, not text), and whether anyone later confirmed it.

**[Website](https://franciscopecora.github.io/atlas-project/)** · [Live map](https://franciscopecora.github.io/atlas-project/map.html) · [Public data](release/DATA_DICTIONARY.md) · [Failure analysis](FAILURES.md) · [Detailed results](docs/RESULTS.md) · [Pre-registered spec](SPEC.md)

## Result

I wrote the metrics and targets down before writing any pipeline code. I froze a held-out test set on 17 November 2026 (commit `9da84a1`) and scored it exactly once, on 19 November. Version 1.1 (22 November) adds two more sources, each with its own test set, frozen before any system ran on it and scored once ([SPEC amendment A2](docs/spec_amendment_A2.md)).

- **The ledger:** 5,778 events from 332 daily reports, 19 July to 15 November 2026, from three official sources: the Ukrainian General Staff (4,550 events), the Ukrainian Air Force's overnight air-attack reports (362) and the Russian Ministry of Defence's Telegram channel (866, including 171 claimed captures of settlements). 4,928 of them are placed on the map.
- **Accuracy:** on 12 unseen General Staff reports the shipped pipeline finds events with an F1 of **0.891** (95% interval 0.869 to 0.917), against a target of 0.80.
- **The main hypothesis failed, on all three sources.** I expected verification layers to beat a single prompt by 0.08 F1. They did the opposite: on the General Staff one free-form prompt scored **0.962**, and on the two new sources the shipped pipeline again scored below plain schema extraction (Air Force 0.787 against 0.857, Russian MoD 0.716 against 0.849). The model verifier drops whole correct records: 40 of 133 on the Russian test reports.
- **Where structure helps:** on the formulaic General Staff text the free-form prompt (B2) wins; on the varied Russian posts schema-constrained extraction (S1) beats it, 0.849 against 0.784.
- **The confirmation question still cannot be answered.** The ledger now holds 148 Russian capture claims that rule 7b can follow, but none of the three sources reports independent geolocations, so there is nothing to pair them with. That needs ISW reports.
- **The two sides describe the same places in different terms** (exploratory, not pre-registered). Of 166 Russian capture claims placed on the map, 77 had a General Staff assault reported within 5 km in the 30 days before (median 3 days), and 76 in the 30 days after: Ukraine kept reporting assaults it repelled at places Russia said it had taken. Assault reports do not say who holds a place, so this is a contrast between the feeds, not a verdict on either ([src/cross_source.py](src/cross_source.py)).
- **Cost:** 1.6 US cents per General Staff report for the shipped pipeline at batch price, against a target of 10 euro cents; under 1 cent for the new sources.

| System (test split, 12 reports, 621 events) | Precision | Recall | F1 (95% interval) | USD per report |
| --- | --- | --- | --- | --- |
| B0, rules and gazetteer | 0.998 | 0.765 | 0.866 (0.800 to 0.929) | 0 |
| B1, GLiNER2 and rules | 0.961 | 0.836 | 0.894 (0.849 to 0.926) | 0 |
| B2, one free-form prompt | 0.991 | 0.934 | **0.962** (0.951 to 0.973) | 0.0030 |
| S1, schema-constrained extraction | 0.985 | 0.929 | 0.956 (0.944 to 0.969) | 0.0034 |
| S2, S1 plus deterministic checks | 0.990 | 0.915 | 0.951 (0.932 to 0.968) | 0.0034 |
| S3-H, S2 plus model verifier and geocoder (shipped) | 0.939 | 0.847 | 0.891 (0.869 to 0.917) | 0.0156 |

**Version 1.1, the two new sources** (test splits of 12 reports each, scored once on 22 November; B0 and B1 are General Staff rules and are not run):

| System | Air Force, 54 events: F1 (95% interval) | Russian MoD, 138 events: F1 (95% interval) |
| --- | --- | --- |
| B2, one free-form prompt | **0.891** (0.814 to 0.956) | 0.784 (0.701 to 0.868) |
| S1, schema-constrained extraction | 0.857 (0.787 to 0.931) | **0.849** (0.806 to 0.901) |
| S2, S1 plus deterministic checks | 0.857 (0.787 to 0.931) | 0.849 (0.806 to 0.901) |
| S3-H, shipped | 0.787 (0.731 to 0.846) | 0.716 (0.652 to 0.783) |

An event counts as found when the type matches, the place is within 10 km and the date is within 1 day (SPEC 5.1). Intervals come from resampling whole reports. Scores are per source and never pooled.

## Why this matters

Open-source analysts read the same daily reports by hand and copy them into spreadsheets, and in that step the line between "Russia says", "Ukraine says" and "seen on video" tends to blur. Atlas keeps that line in every record (`epistemic_status`), and it points to the evidence by character offsets and a hash. Anyone can therefore check a record against the original without the dataset republishing the text.

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

The five worst General Staff error patterns, and four more for the Air Force and Russian MoD sources, are in [FAILURES.md](FAILURES.md). On the Russian posts the biggest loss is the verifier dropping strikes on ports and ships whose quote is a list line without its verb, the same fault as pattern 2 below. The largest General Staff patterns:

1. **Wrong village with the same name.** About 1 in 6 places with a common name, such as Novoselivka, lands on the wrong village.
2. **Quotes cut down to a bare place name.** The verifier then cannot see the verb and drops the record.
3. **The model verifier removes fields that were correct.** Its value lies in dropping whole bad records, not in fixing fields.

Two targets were missed: speed (112 s per report on live calls, against a target of 60 s) and the H1 margin. Geocoding accuracy could not be measured on the test set. Details are in [docs/RESULTS.md](docs/RESULTS.md).

## Limits

- This measures what the reports claim, not what happened on the ground.
- The answer key for the General Staff reports was drafted by a model and audited by sample (2 of 130 sampled events wrong on dev, 1 of 28 on test; [SPEC amendment A1](docs/spec_amendment_A1.md)). The key and the systems are models from one family, so agreement comes easier than it would against a human key, and every score is likely somewhat high.
- There is one annotator, who does not read Ukrainian and worked from a machine translation.
- The three sources are all official and all claims: nothing in the ledger is independently confirmed. The answer keys for the two new sources were made the same way (1 of 59 judged test events wrong across both), and their test sets are small (54 and 138 events).
- The Air Force reports name almost no places, so their events are shown as a nightly chart, not on the map. The General Staff names places for ground assaults but gives shelling and air strikes mostly as front-wide totals, so the map shows where each source names places, not where fighting happens.

## Intended use

Research on the reliability of open-source battlefield reporting. It is not for targeting or operational use. The map leaves out anything dated within 48 hours of the build, and the data names no individuals.

## Data

[`release/ledger_public.parquet`](release/ledger_public.parquet) holds one row per event with a [JSON Schema](release/ledger_public.schema.json) and a [data dictionary](release/DATA_DICTIONARY.md). It contains no text from the reports: the evidence is given as offsets into the cleaned text, with that text's SHA-256 and the report URL. The release is built from a whitelist of fields, and a check refuses any Cyrillic string or any value copied from the reports.

Sources: Ukrainian General Staff operational updates and Ukrainian Air Force overnight reports republished by [ArmyInform](https://armyinform.com.ua) under CC BY 4.0; the Russian Ministry of Defence's public Telegram channel, which states no licence (no text from it is published); places from GeoNames (CC BY 4.0) and OpenStreetMap (ODbL). Source text stays local and is never committed. `release/air_nights.csv` holds the Air Force numbers per night.

## Reproduce

Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
make data
make all
```

- `make data` collects and cleans the reports (slow, network). Building the gazetteer needs GeoNames `UA.txt` in `data/raw/gazetteer/` (see `src/gazetteer.py`).
- `make all` runs lint, the tests (323), the dev-split scores and the site data.
- Without the private saved model runs, the scorer scores the two baselines and says which systems it skipped.
- `make fresh-clone` repeats `make all` in a clean clone that holds only the dev reports and the gazetteer.
- The paid steps are `make ledger` (the full corpus through the Batches API: about 1.7 USD for the General Staff, 1.2 USD for the two new sources) and `make eval-test SOURCE=gsu|af|rumod`, which refuses to run a second time for a source.

## Status

Version 1 was released on 19 November 2026 with the General Staff; version 1.1 on 22 November adds the Ukrainian Air Force and the Russian Ministry of Defence. Version 2 will add ISW's daily assessments, if ISW grants permission, to answer the confirmation question (H2): how often, and how fast, Russian claims of advances are later geolocated.

**A possible extension: incidents in Europe that a government attributed to Russia.** Since 2022, European authorities have publicly attributed sabotage, arson, cable damage, drone incursions and cyber attacks to Russia. These are the same kind of object as a ledger record: a claim, the authority that made it, a place, a date and the evidence it points to. The question would be who attributed what, how firmly, and whether the attribution was later upheld. It is not built, for three reasons stated plainly. There is no daily report to collect: attributions are spread over statements by governments, prosecutors and intelligence services in many languages. The schema would need new fields (the attributing authority, the firmness of the attribution from suspected to charged to convicted, and any denial), which means a SPEC amendment before any code. And there is no answer key, so nothing about it could be measured yet. A first step would be a pilot of about 30 incidents from one existing public list, labelled by hand, with its metrics written down first as for the rest of this project.

Built by Francisco Pecora with Claude Code. Decisions and their reasons are logged in [DECISIONS.md](DECISIONS.md).

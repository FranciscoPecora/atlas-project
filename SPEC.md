# Claimline SPEC

Frozen 16 November 2026, before any pipeline code. Metric definitions and numeric targets in this file do not change after this commit. If one turns out to be wrong, the change goes in a new dated section at the end ("Amendments") with the reason, and the original text stays.

Where this file and PLAN.md disagree, this file wins.

## 1. Corpus and windows

| Item | Value |
| --- | --- |
| Corpus window | Reports dated 2026-07-19 to 2026-11-15 inclusive (120 days) |
| Analysis window for claims | Claims in reports dated 2026-07-19 to 2026-10-16 inclusive (first 90 days) |
| Observation-only window | 2026-10-17 to 2026-11-15. Used only to observe confirmations of earlier claims. |
| Source ISW | Russian Offensive Campaign Assessment, `https://understandingwar.org/research/russia-ukraine/russian-offensive-campaign-assessment-<month>-<d>-<yyyy>/`. Collection is conditional on written permission (docs/permissions.md). |
| Source GSU | Ukrainian General Staff 08:00 operational update ("станом на 08.00"), as republished by ArmyInform (CC BY 4.0). One report per date: the post published on that date whose body states the operational information as of 08:00 ("Оперативна інформація станом на 08:00" in any inflection, hour written 08:00, 8:00 or 08.00). Candidate posts are ranked by slug keywords listed in config.yaml; the first whose body has the statement is used. Found through `https://armyinform.com.ua/sitemap.xml`, never through `/wp-json/` or site search. |
| Report date | The date in the ISW title; the publication date of the GSU post. |
| Data cutoff | Stored per report when the text states one; null otherwise. GSU 08:00 reports have cutoff 08:00 Kyiv time on the report date. |
| Default event date | When the text gives no date: ISW = report date; GSU 08:00 report = report date minus 1 day (it summarises the previous day). |

## 2. Schema

The normative schema is the Pydantic code in Appendix A. Appendix B is its exported JSON Schema (the `output_format` sent to the API). `src/schema.py` must export a JSON Schema byte-identical to Appendix B; a test enforces this.

Two models:

- `ExtractedEvent` is what the model returns. It holds no offsets, no coordinates, no report metadata.
- `LedgerEvent` extends it with fields computed by code: ids, source, section, sector, report date, `lat`, `lon`, `gazetteer_id`, `unit_ids`, `evidence_start`, `evidence_end`, `text_sha256`, `source_url`, `footnote_ref`, `system`, `run_id`.

API constraints checked against this schema: 12 optional fields (limit 24), 10 union-type fields (limit 16). Enums are compared case-insensitively. Ranges (`geo_precision` in 1..3, `quantity` >= 0) are validated in Pydantic after parsing, not by the API.

The published ledger excludes `evidence_quote`. Nothing published contains source text.

### 2.1 Event unit

One event per place per day. "Russian forces attacked near A, B and C on November 14 and 15" is six events (3 places x 2 days) sharing one `evidence_quote`.

A sentence with no place produces one event per day with `location_text = null`. A sentence with no date uses the default event date (section 1).

### 2.2 Field rules

| Field | Rule |
| --- | --- |
| `epistemic_status` | Follows the wording, not the annotator's belief. Trigger phrases are in docs/annotation_guideline.md. |
| `location_text` | Must occur inside `evidence_quote` after normalisation (2.3). |
| `geo_precision` | 1 = a named settlement or point. 2 = "near", "toward", "in the direction of", "northwest of" a settlement, or a named direction or area; geocoded to the named settlement's point. 3 = an oblast only; geocoded to the oblast centroid. |
| `quantity` | Must occur inside `evidence_quote` as digits (thousands separators allowed: space, comma, thin space) or as a number word from Appendix C. |
| `evidence_quote` | An exact contiguous span of the section text. |
| `evidence_start`, `evidence_end` | Computed by code: character offsets into the cleaned report text (not the section), end exclusive. |
| `text_sha256` | SHA-256 of the UTF-8 cleaned report text the offsets index into. |

### 2.3 Normalisation for quote matching

Applied to both the quote and the text before searching, with an offset map back to the original text: Unicode NFC; all whitespace runs to one space; curly quotes, guillemets and backticks to `"`; apostrophe variants (U+2019, U+02BC, U+0060, U+2018) to `'`; dashes (U+2010 to U+2015, U+2212) to `-`. Case is preserved. If the normalised quote occurs more than once in the section, the first occurrence is used and the event is flagged `ambiguous_offset`.

## 3. Sections and sectors

Reports are segmented at H2 and H3 headings. Each section is assigned one sector by the first matching rule, applied case-insensitively to the heading text:

| Order | Heading contains | Sector |
| --- | --- | --- |
| 1 | "Toplines" or "Key Takeaways" | SUMMARY |
| 2 | "Belarus" | BELARUS |
| 3 | "Russian Federation" | RU_INTERIOR |
| 4 | "Northern Axis" | NORTH |
| 5 | "Oskil" | OSKIL |
| 6 | "Kharkiv" | KHARKIV |
| 7 | "Donetsk", "Fortress Belt" or "Dnipropetrovsk" | DONETSK |
| 8 | "Southern Axis" | SOUTH |
| 9 | "Air, Missile" or "Drone Campaign" | AIR |
| 10 | anything else | UNMAPPED: segmentation raises an error and the report is logged for review |

A heading with no body text before the next heading is a container: it gets no sector and is skipped, so it cannot raise UNMAPPED. Text before the first heading (title, date) is sector SUMMARY. H4 headings ("Russian objective: ...") are body text, not section breaks. Consecutive sections with the same sector are merged into one unit. Rules may gain keywords for new heading wordings (logged in DECISIONS.md), but the sector list and rotation do not change.

GSU reports are not segmented for sampling: the whole report is one unit (sector FULL).

SUMMARY and BELARUS are extracted in the full run but never sampled for the gold set.

## 4. Gold set

### 4.1 Sampling design

- 30 ISW reports, every 4th day from 2026-07-19 (day offsets 0, 4, ..., 116).
- 15 GSU reports, every 8th day from 2026-07-21 (day offsets 2, 10, ..., 114), labelled in full.
- ISW sectors per report: the 7 sampled sectors sorted alphabetically are shuffled with `random.Random(20261116).shuffle` (Python 3.12). Report i (0-based, in date order) takes `perm[(2i) % 7]` and `perm[(2i+1) % 7]`.
- If a drawn sector is absent from a report, take the next sector in `perm` order not already drawn for that report.
- Target: at least 700 gold events. If short, add the ISW reports at day offsets 2, 6, ..., 118 in date order, continuing the same rotation index, until the target is met. Sections are never picked by hand.
- If ISW permission is refused: GSU reports only for the gold set, plus a smaller ISW evaluation sample if permission covers that, recorded as an amendment.
- If a sampled report is missing from the corpus: take the next available date for that source and log it.

Permutation produced by the seed: `['AIR', 'RU_INTERIOR', 'OSKIL', 'KHARKIV', 'NORTH', 'SOUTH', 'DONETSK']`.

Generator (run with `uv run --no-project --python 3.12 python -I`):

```python
import random
from datetime import date, timedelta

SEED = 20261116
START = date(2026, 7, 19)
SECTORS = sorted(["AIR", "DONETSK", "KHARKIV", "NORTH", "OSKIL", "RU_INTERIOR", "SOUTH"])

perm = SECTORS[:]
random.Random(SEED).shuffle(perm)
isw = [START + timedelta(days=4 * i) for i in range(30)]
gsu = [START + timedelta(days=2 + 8 * i) for i in range(15)]
rows = [(d, "ISW", (perm[(2 * i) % 7], perm[(2 * i + 1) % 7])) for i, d in enumerate(isw)]
rows += [(d, "GSU", ("FULL",)) for d in gsu]
rows.sort(key=lambda r: (r[0], r[1] != "ISW"))
```

### 4.2 Rotation table and date split

The earliest 10 reports are dev. The later 35 are test.

| # | Report date | Source | Sectors | Split |
| --- | --- | --- | --- | --- |
| 1 | 2026-07-19 | ISW | AIR, RU_INTERIOR | dev |
| 2 | 2026-07-21 | GSU | FULL | dev |
| 3 | 2026-07-23 | ISW | OSKIL, KHARKIV | dev |
| 4 | 2026-07-27 | ISW | NORTH, SOUTH | dev |
| 5 | 2026-07-29 | GSU | FULL | dev |
| 6 | 2026-07-31 | ISW | DONETSK, AIR | dev |
| 7 | 2026-08-04 | ISW | RU_INTERIOR, OSKIL | dev |
| 8 | 2026-08-06 | GSU | FULL | dev |
| 9 | 2026-08-08 | ISW | KHARKIV, NORTH | dev |
| 10 | 2026-08-12 | ISW | SOUTH, DONETSK | dev |
| 11 | 2026-08-14 | GSU | FULL | test |
| 12 | 2026-08-16 | ISW | AIR, RU_INTERIOR | test |
| 13 | 2026-08-20 | ISW | OSKIL, KHARKIV | test |
| 14 | 2026-08-22 | GSU | FULL | test |
| 15 | 2026-08-24 | ISW | NORTH, SOUTH | test |
| 16 | 2026-08-28 | ISW | DONETSK, AIR | test |
| 17 | 2026-08-30 | GSU | FULL | test |
| 18 | 2026-09-01 | ISW | RU_INTERIOR, OSKIL | test |
| 19 | 2026-09-05 | ISW | KHARKIV, NORTH | test |
| 20 | 2026-09-07 | GSU | FULL | test |
| 21 | 2026-09-09 | ISW | SOUTH, DONETSK | test |
| 22 | 2026-09-13 | ISW | AIR, RU_INTERIOR | test |
| 23 | 2026-09-15 | GSU | FULL | test |
| 24 | 2026-09-17 | ISW | OSKIL, KHARKIV | test |
| 25 | 2026-09-21 | ISW | NORTH, SOUTH | test |
| 26 | 2026-09-23 | GSU | FULL | test |
| 27 | 2026-09-25 | ISW | DONETSK, AIR | test |
| 28 | 2026-09-29 | ISW | RU_INTERIOR, OSKIL | test |
| 29 | 2026-10-01 | GSU | FULL | test |
| 30 | 2026-10-03 | ISW | KHARKIV, NORTH | test |
| 31 | 2026-10-07 | ISW | SOUTH, DONETSK | test |
| 32 | 2026-10-09 | GSU | FULL | test |
| 33 | 2026-10-11 | ISW | AIR, RU_INTERIOR | test |
| 34 | 2026-10-15 | ISW | OSKIL, KHARKIV | test |
| 35 | 2026-10-17 | GSU | FULL | test |
| 36 | 2026-10-19 | ISW | NORTH, SOUTH | test |
| 37 | 2026-10-23 | ISW | DONETSK, AIR | test |
| 38 | 2026-10-25 | GSU | FULL | test |
| 39 | 2026-10-27 | ISW | RU_INTERIOR, OSKIL | test |
| 40 | 2026-10-31 | ISW | KHARKIV, NORTH | test |
| 41 | 2026-11-02 | GSU | FULL | test |
| 42 | 2026-11-04 | ISW | SOUTH, DONETSK | test |
| 43 | 2026-11-08 | ISW | AIR, RU_INTERIOR | test |
| 44 | 2026-11-10 | GSU | FULL | test |
| 45 | 2026-11-12 | ISW | OSKIL, KHARKIV | test |

Split rule for exported labels: a label belongs to the split of its report's row in this table. Any report not in this table is not gold.

### 4.3 Labelling rules

- Test sections are labelled before any model is run on those reports, and never from model output. Dev sections may be pre-labelled.
- Gold events are geocoded with the same gazetteer as the pipeline; the annotator checks and may override the chosen gazetteer row.
- Consistency: the sampled sections of the 6 reports in rows 1 to 6 (4 ISW, 2 GSU, fixed here) are re-labelled after at least 14 days. Report Cohen's kappa on `event_type` and `epistemic_status` over events matched between the two passes (matching as in 5.1). There is one annotator; kappa measures self-consistency only.
- Minutes per section are logged.

## 5. Evaluation

### 5.1 Event matching

A predicted event p and a gold event g are a valid pair when all hold:

1. same report and same sector;
2. `p.event_type == g.event_type`;
3. `|p.event_date - g.event_date| <= D` days (default D = 1);
4. location: if both have coordinates, haversine(p, g) <= K km (default K = 10); if both have no location, they pass; if exactly one has a location, they fail.

Matching is one-to-one, greedy, closest pair first:

```
pairs = [(dist_km(p, g), |p.date - g.date|, p.id, g.id) for p in P for g in G if valid(p, g)]
   # dist_km = 0 when both locations are null
sort pairs ascending by (dist_km, day_gap, p.id, g.id)
used_p, used_g, matches = {}, {}, []
for (d, gap, p, g) in pairs:
    if p not in used_p and g not in used_g:
        matches.append((p, g)); used_p.add(p); used_g.add(g)
TP = len(matches); FP = |P| - TP; FN = |G| - TP
precision = TP / |P|; recall = TP / |G|; F1 = 2PR / (P + R)   (0 when undefined)
```

Predictions in sections that are not gold units are discarded before matching.

### 5.2 Linking rules

**7a. Duplicate clusters.** Two ledger events are linked if they have the same `event_type`, both have coordinates within 5 km of each other, and their event dates differ by at most 3 days, from any source. Clusters are the connected components of this graph (single linkage; chaining is possible and the maximum cluster diameter is reported).

**7b. Confirmation links.** For each claim c with `event_type = territorial_advance`, `epistemic_status` in {ru_claimed, ua_claimed}, `geo_precision = 1`, and `c.report_date` in the analysis window: the confirmation is the earliest-reported event k with `event_type = territorial_advance`, `epistemic_status = geolocated_confirmed`, the same `gazetteer_id`, the same `actor`, and `c.report_date <= k.report_date <= c.report_date + 30 days`. Lag = `k.report_date - c.report_date` in days. Lag uses report dates because the question is when confirmation became available, not when the event happened. Claims with `geo_precision > 1` are excluded from H2 and their count is reported.

### 5.3 Metrics and targets

| Metric | Definition | Target |
| --- | --- | --- |
| Event F1 | 5.1 with K = 10 km, D = 1 day | >= 0.80 |
| F1 sensitivity | 5.1 on the grid K in {5, 10, 25} km x D in {0, 1, 2} days | Report the grid |
| Epistemic status accuracy | Share of matched pairs with equal `epistemic_status` | >= 0.90 |
| Geocoding accuracy@10 km | Matched pairs where gold `geo_precision = 1`: share with predicted point within 10 km of gold point; median error in km also reported | >= 0.90 |
| Quantity exact match | Matched pairs where gold `quantity` is not null: share with equal quantity | >= 0.95 |
| Unsupported-field rate | 200 records sampled at random from dev-period reports not in the gold set; share of non-null output fields the annotator judges not supported by `evidence_quote` | < 2% |
| Verifier cost in recall | Recall of S1, S2, S3-H, S3-S side by side | Report |
| Annotator consistency | Cohen's kappa, 4.3 | >= 0.75 on both fields |
| External validity | Spearman correlation of daily event counts by oblast against VIINA, over oblast-days in the corpus window | Report, no target |
| Cost | USD per report from API usage fields, converted at the EUR/USD rate in config.yaml on the run date | < 0.10 EUR per report |
| Speed | Wall-clock seconds per report, live API, median | < 60 s |
| H1 | S3 (shipped variant) event F1 >= 0.80 on test, and S3 F1 minus B2 F1 >= 0.08 | Answered with both numbers and intervals |
| H2 | Share of ru_claimed territorial advances (actor RU, 7b) confirmed within 7, 14 and 30 days; median lag per sector | Report with 95% interval. H2 holds if the 14-day share's point estimate is < 0.50 |

### 5.4 Intervals and runs

- 95% intervals are percentile bootstrap, 2,000 resamples, seed 20261116.
- Resampling unit is the report (all events of a report move together). For H2 the unit is the claim's report.
- Tuning uses dev only. Test is scored once per release through `make eval-test`; every run appends to `eval/results.csv` (commit hash, config hash and values, date, split, system).
- A missed target stays in the README with an explanation.

## 6. Systems

| System | Definition |
| --- | --- |
| B0 | Regex verb patterns plus gazetteer lookup, no model |
| B1 | GLiNER2 zero-shot entities plus rules (`fastino/gliner2-base-v1` English, `fastino/gliner2-multi-v1` Ukrainian) |
| B2 | Extraction model, one free-form JSON prompt, no schema, no verification |
| S1 | Schema-constrained extraction (`ExtractionResult` as output format) |
| S2 | S1 plus deterministic verification (2.2, 2.3) |
| S3-H | S2 plus `claude-haiku-5-5` field verifier and geocoder disambiguation |
| S3-S | S2 plus `claude-sonnet-5-5` field verifier and geocoder disambiguation |

Extraction model: `claude-haiku-5-5`. B2 and S1 use the same model and effort. The shipped S3 variant is Haiku unless Sonnet lowers the unsupported-field rate on dev by at least 1 percentage point.

## Amendments

### A1 (2026-11-17, approved by the project owner): machine-made answer key for GSU units

Reason: the annotator reads no Ukrainian and cannot label 15 full GSU reports by hand. Where A1 and sections 4.3 or 5.3 disagree for GSU units, A1 applies. Full text with background: docs/spec_amendment_A1.md.

**4.3, first bullet, replaced for GSU units by:**

- GSU gold labels (dev and test) are made in three steps:
  1. `src/prelabel.py` proposes events by rules (no model).
  2. `src/review.py` has a reviewer model (config `models.gold_review`, a larger model
     than the extraction model) keep, fix, remove or add events under
     docs/annotation_guideline.md. Code, not the model, computes offsets and rejects any
     event whose quote, place or quantity is not in the text.
  3. `src/audit.py` draws a seeded random sample per split: 30 events and 10 paragraphs.
     The annotator judges each event Right or Wrong and each paragraph Complete or
     Missing something, reading a machine translation.
- The key is accepted for a split if the audited event error rate and the audited
  paragraph miss rate are both at most 5% (point estimates; 95% Wilson intervals are
  reported). If either is above 5%, the errors found are fixed, the reviewer prompt may be
  changed **on dev only**, and a fresh sample is drawn. Test-split audits never feed back
  into prompts.
- The GSU test key is made once, before any evaluated system (B0 to S3) is run on those
  reports. The reviewer model and the translation model do run on them; that is the
  change from the original rule.

**4.3, consistency bullet, and 5.3 "Annotator consistency", for GSU units:**

- Cohen's kappa over two human passes is not computed for GSU units, because no human
  labels them. It is replaced by the audit rates above and by reviewer stability: the
  reviewer is run a second time on the 2 GSU reports in rows 1 to 6, and kappa on
  `event_type` and `epistemic_status` between the two runs is reported, target >= 0.75.

**5.3, added limit, reported in the README next to every GSU score:**

- GSU gold is a machine-made key audited by sample, not a human key. The reviewer and
  the evaluated systems are models from the same family, so shared mistakes can raise
  measured F1. The rule baseline B0 shares the pre-fill's patterns and is favoured the
  same way. The audit reads a machine translation, so it cannot catch translation errors.

**Not changed:** ISW units (still labelled by hand, in English), metric definitions and targets other than
the consistency row, the dev/test split, and the rule that test gold files are opened only
by `eval/score.py`.

## Appendix A. Schema (normative)

```python
"""Claimline event schema. Normative copy lives in SPEC.md section 2."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventType(StrEnum):
    ground_assault = "ground_assault"
    territorial_advance = "territorial_advance"
    withdrawal = "withdrawal"
    missile_strike = "missile_strike"
    drone_strike = "drone_strike"
    air_strike = "air_strike"
    shelling = "shelling"
    air_defence_interception = "air_defence_interception"
    force_movement = "force_movement"
    logistics_or_infrastructure_strike = "logistics_or_infrastructure_strike"
    naval_event = "naval_event"
    other = "other"


class EpistemicStatus(StrEnum):
    ru_claimed = "ru_claimed"
    ua_claimed = "ua_claimed"
    third_party_claimed = "third_party_claimed"
    geolocated_confirmed = "geolocated_confirmed"
    analyst_assessed = "analyst_assessed"


class Side(StrEnum):
    RU = "RU"
    UA = "UA"
    other = "other"


def _casefold_enum(enum_cls: type[StrEnum], value: object) -> object:
    """Map a string onto an enum member ignoring case. The API does not guarantee enum case."""
    if isinstance(value, str):
        for member in enum_cls:
            if member.value.lower() == value.strip().lower():
                return member
    return value


class UnitMention(BaseModel):
    name: str = Field(description="Unit name exactly as written in the evidence quote")
    echelon: str | None = Field(None, description="e.g. brigade, regiment, battalion, division")
    branch: str | None = Field(None, description="e.g. VDV, naval infantry, motorized rifle")


class ExtractedEvent(BaseModel):
    """What the extraction model returns. No offsets, no coordinates, no report metadata."""

    model_config = ConfigDict(extra="forbid")

    event_type: EventType
    epistemic_status: EpistemicStatus
    claim_source: str | None = Field(
        None, description="Who made the claim as the text names them, e.g. 'Russian MoD'"
    )
    actor: Side | None = None
    actor_text: str | None = None
    target: Side | None = None
    target_text: str | None = None
    location_text: str | None = Field(
        None, description="Place name exactly as written; must appear inside evidence_quote"
    )
    geo_precision: int | None = Field(None, description="1 settlement, 2 direction or area, 3 oblast")
    event_date: date
    units: list[UnitMention] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    quantity: int | None = Field(None, description="Must appear inside evidence_quote")
    evidence_quote: str = Field(description="Exact contiguous text copied from the section")

    @field_validator("event_type", mode="before")
    @classmethod
    def _event_type_case(cls, v: object) -> object:
        return _casefold_enum(EventType, v)

    @field_validator("epistemic_status", mode="before")
    @classmethod
    def _status_case(cls, v: object) -> object:
        return _casefold_enum(EpistemicStatus, v)

    @field_validator("actor", "target", mode="before")
    @classmethod
    def _side_case(cls, v: object) -> object:
        return _casefold_enum(Side, v)

    @field_validator("geo_precision")
    @classmethod
    def _precision_range(cls, v: int | None) -> int | None:
        if v is not None and v not in (1, 2, 3):
            raise ValueError("geo_precision must be 1, 2 or 3")
        return v

    @field_validator("quantity")
    @classmethod
    def _quantity_nonneg(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("quantity must be >= 0")
        return v

    @field_validator("evidence_quote")
    @classmethod
    def _quote_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("evidence_quote must not be empty")
        return v


class ExtractionResult(BaseModel):
    """Top-level output_format for client.messages.parse: one call per section."""

    events: list[ExtractedEvent]


class LedgerEvent(ExtractedEvent):
    """One row of the ledger. Fields below are filled by code, never by a model."""

    event_id: str
    report_id: str
    source: Annotated[str, Field(pattern="^(isw|gsu)$")]
    section: str
    sector: str
    report_date: date
    lat: float | None = None
    lon: float | None = None
    gazetteer_id: str | None = None
    unit_ids: list[str] = Field(default_factory=list)
    evidence_start: int
    evidence_end: int
    text_sha256: str
    source_url: str
    footnote_ref: str | None = None
    system: str
    run_id: str


PUBLIC_EXCLUDED_FIELDS = frozenset({"evidence_quote"})
```

## Appendix B. Exported JSON Schema of `ExtractionResult`

```json
{
  "$defs": {
    "EpistemicStatus": {
      "enum": [
        "ru_claimed",
        "ua_claimed",
        "third_party_claimed",
        "geolocated_confirmed",
        "analyst_assessed"
      ],
      "title": "EpistemicStatus",
      "type": "string"
    },
    "EventType": {
      "enum": [
        "ground_assault",
        "territorial_advance",
        "withdrawal",
        "missile_strike",
        "drone_strike",
        "air_strike",
        "shelling",
        "air_defence_interception",
        "force_movement",
        "logistics_or_infrastructure_strike",
        "naval_event",
        "other"
      ],
      "title": "EventType",
      "type": "string"
    },
    "ExtractedEvent": {
      "additionalProperties": false,
      "description": "What the extraction model returns. No offsets, no coordinates, no report metadata.",
      "properties": {
        "event_type": {
          "$ref": "#/$defs/EventType"
        },
        "epistemic_status": {
          "$ref": "#/$defs/EpistemicStatus"
        },
        "claim_source": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Who made the claim as the text names them, e.g. 'Russian MoD'",
          "title": "Claim Source"
        },
        "actor": {
          "anyOf": [
            {
              "$ref": "#/$defs/Side"
            },
            {
              "type": "null"
            }
          ],
          "default": null
        },
        "actor_text": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Actor Text"
        },
        "target": {
          "anyOf": [
            {
              "$ref": "#/$defs/Side"
            },
            {
              "type": "null"
            }
          ],
          "default": null
        },
        "target_text": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Target Text"
        },
        "location_text": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Place name exactly as written; must appear inside evidence_quote",
          "title": "Location Text"
        },
        "geo_precision": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "1 settlement, 2 direction or area, 3 oblast",
          "title": "Geo Precision"
        },
        "event_date": {
          "format": "date",
          "title": "Event Date",
          "type": "string"
        },
        "units": {
          "items": {
            "$ref": "#/$defs/UnitMention"
          },
          "title": "Units",
          "type": "array"
        },
        "equipment": {
          "items": {
            "type": "string"
          },
          "title": "Equipment",
          "type": "array"
        },
        "quantity": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "Must appear inside evidence_quote",
          "title": "Quantity"
        },
        "evidence_quote": {
          "description": "Exact contiguous text copied from the section",
          "title": "Evidence Quote",
          "type": "string"
        }
      },
      "required": [
        "event_type",
        "epistemic_status",
        "event_date",
        "evidence_quote"
      ],
      "title": "ExtractedEvent",
      "type": "object"
    },
    "Side": {
      "enum": [
        "RU",
        "UA",
        "other"
      ],
      "title": "Side",
      "type": "string"
    },
    "UnitMention": {
      "properties": {
        "name": {
          "description": "Unit name exactly as written in the evidence quote",
          "title": "Name",
          "type": "string"
        },
        "echelon": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "e.g. brigade, regiment, battalion, division",
          "title": "Echelon"
        },
        "branch": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "e.g. VDV, naval infantry, motorized rifle",
          "title": "Branch"
        }
      },
      "required": [
        "name"
      ],
      "title": "UnitMention",
      "type": "object"
    }
  },
  "description": "Top-level output_format for client.messages.parse: one call per section.",
  "properties": {
    "events": {
      "items": {
        "$ref": "#/$defs/ExtractedEvent"
      },
      "title": "Events",
      "type": "array"
    }
  },
  "required": [
    "events"
  ],
  "title": "ExtractionResult",
  "type": "object"
}
```

## Appendix C. Number words accepted for `quantity`

English (case-insensitive, whole word): zero 0, one 1, two 2, three 3, four 4, five 5, six 6, seven 7, eight 8, nine 9, ten 10, eleven 11, twelve 12, thirteen 13, fourteen 14, fifteen 15, sixteen 16, seventeen 17, eighteen 18, nineteen 19, twenty 20, thirty 30, forty 40, fifty 50, sixty 60, seventy 70, eighty 80, ninety 90, hundred 100, dozen 12.

Ukrainian (case-insensitive, matched as word prefix to cover inflection): одн 1, дв 2, тр 3, чотир 4, п'ят 5, шіст/шест 6, сім/сем 7, вісім/восьм 8, дев'ят 9, десят 10, дванадцят 12, двадцят 20, тридцят 30, сорок 40, п'ятдесят 50, сто 100.

Ukrainian stems are matched only against the stem table for the record's value (a quantity of 3 accepts a word starting "тр", not any number word). Short stems can match unrelated words; the unsupported-field audit (5.3) measures any false acceptance this causes. Anything else must appear as digits.

### A2 (2026-11-19, approved by the project owner): sources AF and RUMOD

Reason: the GSU reports hold no Russian claims and no missile or drone events, so those
parts of the schema stay empty. A2 adds the Ukrainian Air Force overnight report (AF, via
ArmyInform, CC BY 4.0) and the Russian Ministry of Defence public Telegram channel
(RUMOD), defines their report date and default event date, lets `LedgerEvent.source`
take `af` and `rumod`, and gives each a 15-report gold set on the GSU dates (3 dev, 12
test) made by the A1 method without rule pre-fills. Systems B2, S1, S2 and S3-H are scored
per source; each test split is scored once, never pooled with GSU. Metric definitions,
targets, H1, H2 and the GSU results do not change. Full text:
docs/spec_amendment_A2.md.

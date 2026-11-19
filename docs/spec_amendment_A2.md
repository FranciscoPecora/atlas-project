# Amendment A2: two more sources, Air Force (AF) and Russian MoD (RUMOD)

Status: **approved by Francisco Pecora on 2026-11-19** ("Both, Air Force first") and
recorded in SPEC.md, Amendments. Written before any AF or RUMOD text was labelled.

## Why

The General Staff (GSU) reports carry no Russian claims and almost no missile or drone
events: in the version 1 ledger every event is `ua_claimed`, and `missile_strike`,
`drone_strike` and `air_defence_interception` are empty. Two public daily sources fill
those gaps with the same principles: text kept local, events tied to it by offsets and a
hash, nothing published but derived records.

## What changes

**Section 1, two sources added:**

| Item | Value |
| --- | --- |
| Source AF | Ukrainian Air Force report on the overnight air attack, as republished by ArmyInform (CC BY 4.0). One report per date: among the posts published on that date (found through the same monthly sitemaps as GSU, ranked by slug keywords in config.yaml), the first whose body states the night ("У ніч на <day> <month>") and attributes it to the Air Force ("Повітряні сили" in any inflection). |
| Source RUMOD | Russian Ministry of Defence public Telegram channel, read through its public web preview `https://t.me/s/mod_russia`. One report per date: every post timestamped on that date in Moscow time (UTC+3) whose text matches a claim pattern in config.yaml (captured settlements, air-defence interceptions, strike claims, the daily digest), joined in post order. Each post is preceded in the cleaned text by a line holding its URL. No licence is stated; the text is stored locally and never published, as for every source. |
| Report date | AF: the publication date of the post. RUMOD: the Moscow-time date of the posts. |
| Default event date | AF: the report date (the night ends on it). RUMOD: the report date. A date in the text always wins. |

**Section 2, schema:** `LedgerEvent.source` accepts `af` and `rumod` (pattern
`^(isw|gsu|af|rumod)$`). For RUMOD, `source_url` is the URL of the post that holds the
evidence, found by code from the offsets; for AF it is the post URL. `ExtractedEvent`
and Appendix B do not change.

**Section 4, gold set, for AF and RUMOD:**

- 15 reports per source on the GSU dates (every 8th day from 2026-07-21); if a date is
  missing, the next available date for that source is used and logged.
- The first 3 are dev and the other 12 are test, as for GSU.
- Labels are made by the A1 method without its first step (there is no rule pre-fill):
  the reviewer model (`models.gold_review`) labels each report under the annotation
  guideline, code computes offsets and rejects any event whose quote, place or quantity
  is not in the text, and the owner audits a seeded random sample per split of 30 events
  (all, if fewer) and 10 paragraphs (AF) or posts (RUMOD), reading a machine translation.
  Acceptance is the same: at most 5% wrong events and at most 5% incomplete paragraphs.
- Each test key is made once, before any evaluated system runs on those reports.
- Guideline additions for these sources are written before the first dev label and
  logged in DECISIONS.md.

**Section 5 and 6, evaluation, for AF and RUMOD:**

- Systems: B2, S1, S2 and S3-H (the shipped system). B0 and B1 are General Staff rules
  and are not run on these sources; B2 is the baseline.
- Each source's test split is scored once, through `make eval-test`, after the owner
  types "run the test set". Each source has its own marker file; the GSU marker
  (eval/test_run.json) stays as it is.
- Scores are reported per source and never pooled with GSU scores.

## Not changed

Metric definitions and targets, H1 and H2 and their rules (7a and 7b), the GSU gold set,
its split and its test result, and the rule that test gold files are opened only by
`eval/score.py`.

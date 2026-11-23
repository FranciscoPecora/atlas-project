# Finding: outline (about 1,200 words, prose to be written by the author)

Version 1.1 (22 November 2026). Version 1 had only the Ukrainian General Staff, so
there was nothing to compare. With the Ukrainian Air Force and the Russian Ministry of
Defence added, the strongest story is the comparison between the two sides' reports.
Three titles:

1. **Repelled or captured? Reading both sides' daily war reports with a language model** (source-led; recommended)
2. **The simple prompt won twice: what verification layers cost when extracting events from war reports** (method-led; the H1 result on three sources)
3. **5,778 claims, zero confirmations: an auditable ledger of official war reporting** (data-led)

The reader is a non-technical analyst. Every number below comes from
[eval/results.csv](../eval/results.csv), [README.md](../README.md),
[DECISIONS.md](../DECISIONS.md) or the public release (`src.cross_source`,
`release/air_nights.csv`); none needs a test key.

## 1. The problem (about 150 words)

- Analysts copy the official daily reports into spreadsheets by hand, every day.
- In that step the line between "Russia says", "Ukraine says" and "seen on video" blurs.
- The question: can a model do the copying, keep the speaker attached to every record, and point to the exact sentence, at a cost an analyst can afford? And does it work equally well on every kind of report?

## 2. What was built (about 200 words)

- **Three official sources, 19 July to 15 November 2026, 332 reports:**
  - Ukrainian General Staff morning update (108 reports, 4,550 events);
  - Ukrainian Air Force overnight air-attack report (102 nights, 362 events);
  - Russian Ministry of Defence Telegram channel (866 events, 171 of them claimed captures of settlements).
- **Output:** 5,778 events, 4,928 on the map. Each carries who claims it (`ua_claimed` or `ru_claimed`) and character offsets into the source, so it can be checked without the dataset republishing the text.
- **Rules that keep it honest:** the model copies a quote; code finds it in the text or rejects the record; coordinates come from a gazetteer, never from the model.
- **Cost:** about 1.7 USD for the General Staff corpus and 1.18 USD for the two new sources.

## 3. Finding 1: the two sides do not describe the same war (about 250 words)

- **What each side reports.** The General Staff reports assaults repelled: 4,103 of its 4,550 events are ground assaults, and not one is ground lost or gained. The Russian MoD reports captures (171), interceptions (246), strikes on infrastructure (169) and naval events (121), and almost no assaults (38).
- **Where they meet.** Of the 166 Russian capture claims placed on the map, 77 had a General Staff assault reported within 5 km in the 30 days before the claim (median 3 days). 76 also had one reported in the 30 days after it: the General Staff still reported fighting at or near a place after Russia said it had taken it.
- **What that means, and what it does not.** It does not show either side is wrong. "Assault in the area of" a village does not say who holds it, and some places of a shared name sit at the wrong village. It shows that neither feed alone tells an analyst what changed hands.
- **Caveat to print:** this check is exploratory. It was not pre-registered and has no answer key.

## 4. Finding 2: the simple prompt beat the pipeline, on all three sources (about 250 words)

- **Pre-registered expectation (H1):** verification layers add at least 0.08 F1 over a single prompt.
- **Test results (each set frozen before any system ran and scored once):**

  | Source (test events) | One free-form prompt (B2) | Schema extraction (S1) | Shipped pipeline (S3-H) |
  | --- | --- | --- | --- |
  | General Staff (621) | **0.962** | 0.956 | 0.891 |
  | Air Force (54) | **0.891** | 0.857 | 0.787 |
  | Russian MoD (138) | 0.784 | **0.849** | 0.716 |

- **Where the loss comes from:** the model verifier drops whole correct records (40 of 133 on the Russian test reports, all for the event type) and the geocoder moves some events to a village of the same name.
- **The twist:** on the formulaic General Staff text the free-form prompt wins; on the varied Russian posts a fixed output schema wins by 0.065. Structure pays off where the text is irregular, and verification did not pay off anywhere.
- **Lesson for analysts:** measure the simple baseline on each source before buying complexity.

## 5. Finding 3: the air war in numbers (about 150 words)

- Air Force reports, 102 nights: 15,235 drones and 366 missiles launched, 10,881 shot down, hits recorded by 407 drones and 24 missiles.
- These reports name almost no places (19 of 362 events located), so they appear as a nightly chart, not on the map.
- **Caveat:** 10 of the 102 nights have no drone launch count because extraction missed it, so the totals are a lower bound.

## 6. What could not be answered (about 100 words)

- H2, the core question: how often, and how fast, are Russian claims of advances confirmed by geolocation?
- The ledger now holds **148 eligible Russian claims** for rule 7b, but **0 confirmations**: none of the three official sources reports independent geolocations.
- Answering H2 needs ISW's daily assessments (version 2, pending permission).

## 7. Limits (about 100 words)

- Answer keys were drafted by a model and audited by sample (General Staff 1 of 28 test events wrong; Air Force 0 of 30; Russian MoD 1 of 29). The key and the systems are from one model family, so scores are likely somewhat high.
- One annotator, who reads neither Ukrainian nor Russian and worked from a machine translation.
- The two new test sets are small (54 and 138 events), so their intervals are wide.
- About 1 in 6 places with a common name lands on the wrong village.
- The ledger records what each side claims, not what happened.

## 8. Takeaway (about 50 words)

- Extraction is cheap (cents per report) and accurate enough (F1 0.72 to 0.96).
- The hard part is not reading the sentence but knowing who is speaking, placing it on the right village, and seeing that two official feeds describe different wars.
- The offsets and the 48-hour-delayed map let any reader check a claim against its source.

## Figures to include

1. The map with the source filter set to Russian MoD, Donetsk or Kharkiv zoomed (screenshot of the live site).
2. Grouped bar chart: F1 with intervals for B2, S1 and S3-H on each of the three test sets (the table in section 4).
3. The Air Force nightly chart from the site (launched against shot down).

# Finding: outline (about 1,200 words, prose to be written by the author)

PLAN's working title, "Claimed versus confirmed: 90 days of advances on the Ukrainian
front", no longer fits. The General Staff corpus has no Russian claims and no
geolocated confirmations, so there is nothing to pair. Three titles that fit what was
actually found:

1. **One prompt is enough: what a language model can and cannot read from Ukraine's daily war reports** (method-led; the H1 result)
2. **4,550 claims in 108 days: building an auditable ledger of the General Staff's front-line reports** (data-led)
3. **Before you count the assaults: what automated reading of war reports gets wrong** (failure-led; best for an analyst audience)

The reader is a non-technical analyst. Every number below comes from
[eval/results.csv](../eval/results.csv), [docs/RESULTS.md](RESULTS.md) or the
public release, and none needs the test key.

## 1. The problem (about 150 words)

- Analysts copy the General Staff's 08:00 update into spreadsheets by hand, every day.
- Copying loses who is speaking: a Ukrainian claim, a Russian claim and a geolocated video end up in the same column.
- The question: can a model do the copying, keep the speaker attached, and point to the exact sentence, at a cost an analyst can afford?

## 2. What was built (about 200 words)

- **Corpus:** 108 daily reports from 19 July to 15 November 2026, via ArmyInform (CC BY 4.0). On 12 of the 120 days no post states the 08:00 cutoff, so those days are missing.
- **Output:** 4,550 events at 447 places, 4,448 of them on the map. Each event carries a claim status and character offsets into the report, so it can be checked without the dataset republishing the text.
- **Rules that keep it honest:** the model copies a quote; code finds it in the text (if the quote is not there, the record is rejected); coordinates come from a gazetteer, never from the model.
- **Cost:** about 1.7 USD for the whole corpus; 1.6 US cents per report.

## 3. Finding 1: one prompt beat the pipeline (about 250 words)

- Pre-registered expectation (H1): verification layers add at least 0.08 F1 over a single prompt.
- Test result on 12 unseen reports (621 events): single free-form prompt (B2) F1 **0.962** (0.951 to 0.973); shipped pipeline S3-H **0.891** (0.869 to 0.917). The difference is **-0.071**, and the intervals do not overlap.
- Where the loss comes from:
  - deterministic checks rejected 12 of 586 events, some of them correct;
  - the model verifier and geocoder took F1 from 0.951 to 0.891;
  - false alarms rose from 6 to 34, mostly events placed at a village with the same name as the right one.
- Why: the General Staff writes in one fixed pattern, so the simple prompt was already near the ceiling. Layers that guard against invented facts pay off only where facts get invented.
- Lesson for analysts: measure the simple baseline before buying complexity.

## 4. Finding 2: what the ledger shows, with caveats (about 250 words)

- **Where:** Donetsk oblast 2,331 events, Kharkiv 749, Zaporizhzhia 650, Sumy 493, Dnipropetrovsk 162.
- **What:** 4,103 of 4,550 events are ground assaults; 289 shelling, 94 air strikes. Shelling counts stated in the reports total 3,174.
- **Over time:** events per report fell from about 49 in August to about 33 in November (46.4, 49.3, 43.8, 36.5, 33.4 from July to November). **Caveat:** on some days the extractor lost most records (FAILURES pattern 2), so part of this fall may come from the pipeline, not the front. Do not read it as a trend without checking day by day.
- **Places:** the most-named place, Novoselivka (108 assaults), is a name shared by many villages, which is error pattern 1. A count per village is only as good as the geocoder.
- **Outside check:** against VIINA 2.0 (an independent event dataset), daily counts by oblast correlate at Spearman 0.39 over 2,889 oblast-days. Most of that agreement comes from which oblasts are active at all; day to day it is 0.37 inside Donetsk and near zero elsewhere.

## 5. What could not be answered (about 150 words)

- H2, the core question: how often, and how fast, are Russian claims of advances confirmed by geolocation? Rule 7b found **0 eligible claims**. Every General Staff event is a Ukrainian claim, and none is a territorial advance.
- That is a result about the source, not just a gap: the Ukrainian General Staff reports assaults repelled, not ground lost or gained.
- Answering H2 needs ISW's daily assessments, which tag Russian claims and geolocated footage (version 2, pending permission).

## 6. Limits (about 150 words)

- The test answer key was drafted by a model and audited by sample (1 of 28 sampled test events wrong). It is from the same model family as the systems, so scores are likely somewhat high.
- One annotator, who worked from a machine translation.
- About 1 in 6 places with a common name lands on the wrong village (hand check of 50 dev places: 0.828 within 10 km).
- The ledger records what the General Staff claims, not what happened.

## 7. Takeaway (about 50 words)

- Automated extraction of a formulaic source is cheap (cents per report) and accurate (F1 about 0.9 to 0.96).
- The hard part is not reading the sentence but placing it on the right village and knowing who is speaking.
- The 48-hour-delayed map and the offsets let any reader check a claim against its source.

## Figures to include

1. The map (screenshot of the live site, Donetsk zoomed).
2. Bar chart: F1 with intervals for B0, B1, B2, S1, S2 and S3-H on the test split.
3. Events per report by week, with the caveat from section 4 printed under it.

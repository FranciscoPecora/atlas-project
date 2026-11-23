# Failures

The five worst error patterns of Claimline, found on the dev split (3 General Staff
reports, 175 key events) and in the dev-period field audit, with the test-split
aggregates beside them. The Air Force (AF) and Russian MoD (RUMOD)
sources added in version 1.1 have their own section at the end. Test errors are not inspected one by one: the test key is
opened only by `eval/score.py`.

Examples point into the cleaned report text by report, character offsets and source
URL, with an English paraphrase. The source sentences are not copied here: published
files carry no source text (CLAUDE.md). The text is on ArmyInform under CC BY 4.0; the
offsets index the cleaned text whose SHA-256 is in data/manifest.csv.

## Test-split aggregates (scored once, 2026-11-19)

| | B2 | S1 | S2 | S3-H (shipped) |
| --- | --- | --- | --- | --- |
| Event F1 (95% interval) | 0.962 (0.951 to 0.973) | 0.956 (0.944 to 0.969) | 0.951 (0.932 to 0.968) | 0.891 (0.869 to 0.917) |
| Missed key events (of 621) | 41 | 44 | 53 | 95 |
| False alarms | 5 | 9 | 6 | 34 |

What the aggregates say about the patterns below: S2 rejected 12 of S1's 586 events (4
quote not found, 4 place not in quote, 4 number not in quote) and lost 9 matches
(pattern 4). The S3-H verifier removed 100 fields, among them 14 event types that
dropped their records (pattern 3). S3-H has 34 false alarms against S2's 6. The
verifier only removes, so the rise most likely comes from the geocoder placing events
away from the key's places, where each counts once as a miss and once as a false
alarm (pattern 1). F1 at
25 km rises to 0.906 for S3-H, against 0.891 at 10 km.

## 1. Wrong namesake village (geocoding)

- **What happens.** A place name shared by several villages is put on the wrong one.
  In the hand check of 50 random dev places, 10 of 58 located events (about 1 in 6) sit
  at the wrong namesake, all at names held by several villages. On dev the shipped
  S3-H scores below S2 (F1 0.922 against 0.977), and the drop is this: the previous-day
  rule moved 11 events to another village of the same name.
- **Example.** `gsu-2026-08-06` names a Novoselivka twice, in two paragraphs on two
  different directions (the first at characters 992 to 1043: the enemy attacked toward
  four villages, one of them Novoselivka). Ukraine has many villages of that name; the
  paragraph's other villages are what tells them apart.
- **Cause.** The gazetteer offers many rows for one name; when the oblast named in the
  paragraph does not settle it, the rules fall back to the nearest to the direction's
  main town or to the previous day's events, both weak.
- **Fix.** Use the clue the annotator used: choose the namesake that lies among the
  paragraph's other, uniquely named villages. Then front-line proximity (VIINA's
  territorial-control file holds a daily status per GeoNames village).

## 2. The quote is a bare place name (extraction)

- **What happens.** The extractor copies only the village name as `evidence_quote`,
  without the verb that says what happened. The verifier then judges type, actor and
  target unsupported and drops the record. In the 200-record field audit, Haiku
  dropped 11 of the 12 such records; on 23 July and 9 August most quotes have this
  form, so most records of those reports were lost.
- **Example.** `gsu-2026-07-23`, characters 656 to 665: the quote is one village name
  in the genitive case, cut from a list that follows "the enemy attacked in the areas
  of". 53 records of that report lost their event type for this reason.
- **Cause.** The prompt asks for an exact contiguous quote and for one event per place;
  the model shortens the quote to the place to satisfy both.
- **Fix.** A deterministic rule in S2: a quote must contain the clause's verb, or the
  record is sent back with the full sentence. In the prompt: one worked example where
  three events share one long quote.

## 3. The model verifier removes supported fields

- **What happens.** In the 200-record field audit, the annotator judged 101 of the 145
  fields Haiku removed (and 136 of 177 for Sonnet) to be supported, counting fields in
  dropped records; all 25 fields Haiku set to null without dropping the record were
  supported. The verifier's value is in dropping records with bare quotes (pattern 2),
  not in correcting fields; it also kept 18 actor or target fields judged unsupported.
- **Example.** On `gsu-2026-07-23` the verifier removed `geo_precision` from 52 records,
  with the reason that a bare settlement name suggests precision 1, not 2: the guideline
  sets precision 2 for "in the areas of", which sits outside the quote.
- **Cause.** The verifier sees one quote and the report facts, never the sentence or
  paragraph around it, by design (so it cannot borrow support from elsewhere). Fields
  that rest on context just outside a short quote look unsupported.
- **Fix.** Fix pattern 2 first; with full-sentence quotes most of these fields are
  supported inside the quote. Then let the verifier only drop records, not null single
  fields, unless a dev audit shows the field change is right more often than not.

## 4. Correct events rejected by the deterministic check (S2)

- **What happens.** S2 rejected 2 of S1's 175 dev events, both correct, both because the
  place was not inside the quote. Recall fell from 0.983 to 0.971 and precision did not
  change.
- **Example.** `gsu-2026-08-06`, characters 415 to 445 and 472 to 535: the quotes say
  the aggressor made two air strikes and 75 shelling attacks; the two directions they
  happened on are named at the start of the sentence, outside the quote.
- **Cause.** The extractor cut the quote after the place; the check requires the place
  inside the quote (SPEC 2.2), so the record fails although the event is right.
- **Fix.** The same as pattern 2: quote the whole clause from the place to the verb.
  The check stays: it is what keeps invented places out of the ledger.

## 5. "Activity in the areas of" typed as `other`

- **What happens.** S1's only 3 misses and 3 false alarms on dev are one sentence: the
  key writes three ground assaults, S1 three events of type `other`. B2 has the
  converse kind of miss: the last villages of long "attacking toward" lists left out
  (2 events).
- **Example.** `gsu-2026-07-21`, characters 2193 to 2245: the enemy "showed activity in
  the areas of" three villages.
- **Cause.** The guideline does not say whether "activity" is an assault; the reviewer
  that made the key and the extractor read it differently. It is also the report whose
  other paragraphs are the prompt's worked examples.
- **Fix.** A ruling in the guideline (a hard case with this phrase) and one worked
  example, decided on dev before the next release.

## Not in the five

- **Speed.** S3-H takes a median 112 s per report on live calls (target 60 s) because the
  verifier calls the API once per quote, in sequence. Parallel calls would fix it; the
  full corpus ran through the Batches API, where speed is not measured.
- **Machine-made key.** Agreement between the systems and the General Staff key is
  easier than with a human key: same model family, same guideline (SPEC amendment A1).
  This raises every score in the test table; it is a limit, not a system error.

## Version 1.1: Air Force and Russian MoD

Found on the dev split (3 reports per source: AF 12 key events, RUMOD 36) and in the
ledger; test errors are not inspected one by one. RUMOD examples point to the post
that holds the offsets; the Russian MoD text states no licence and is never published.

**Test-split aggregates (scored once, 2026-11-22).** Counts follow from the scorer's
precision, recall and their n in eval/results.csv.

| | AF B2 | AF S1 | AF S3-H | RUMOD B2 | RUMOD S1 | RUMOD S3-H |
| --- | --- | --- | --- | --- | --- | --- |
| Event F1 | 0.891 | 0.857 | 0.787 | 0.784 | 0.849 | 0.716 |
| Missed key events | 9 of 54 | 12 of 54 | 19 of 54 | 33 of 138 | 23 of 138 | 56 of 138 |
| False alarms | 2 | 2 | 0 | 25 | 18 | 9 |

AF dev has no errors for any system (F1 1.000), so the AF patterns below come from the
ledger. On RUMOD dev S1 has 8 misses and 7 false alarms; S3-H has 18 misses and 4 false
alarms. The verifier dropped 11 of 33 records (8 for the event type, 3 for the date);
on test it dropped 40 of 133.

### 6. RUMOD list items quoted without their verb (verifier drops)

- **What happens.** A strike post opens with one sentence ("struck the following
  targets") and lists the targets below it, one line per port or ship. The extractor
  quotes the line, which names the target but not the strike; the verifier then judges
  the event type unsupported and drops the record. Of the 10 RUMOD dev events that S1
  finds and S3-H misses, 8 are strikes on ports, ships and depots, most of them quoted
  as list lines like the example below.
- **Example.** `rumod-2026-07-29`, characters 2063 to 2105 and 2111 to 2181
  (https://t.me/mod_russia/66085): a fuel tank in the port of Odesa and two cargo ships
  in the port of Pivdennyi, each a line under one strike sentence.
- **Cause.** The same as pattern 2 on General Staff text: one event per item, one
  contiguous quote, and the verb is in another line.
- **Fix.** Give the verifier the lead sentence of the post with each list item, or
  let the quote run from the verb to the item when they are in one post.

### 7. Informal posts typed differently by key and extractor

- **What happens.** The channel mixes formal summaries with front-line slang: "our
  birds catch up with the enemy" (drones), a verb made from the Geran drone's name,
  "our drone pilots cleared the sky". The key and the systems disagree on the event
  type, so each such post counts once as a miss and once as a false alarm.
- **Example.** `rumod-2026-07-21`, characters 2632 to 2695
  (https://t.me/mod_russia/65797): the key types it `drone_strike`, S1 `shelling`.
- **Cause.** The guideline's verbs come from General Staff reports; section 8.4 does
  not list RUMOD's slang.
- **Fix.** A short list of RUMOD terms and their event types in section 8.4, decided
  on dev.

### 8. Repeat and recap posts counted again

- **What happens.** The channel announces a capture, then posts "details of the
  liberation" of the same places later. The repeat rule (guideline 8.4) labels an
  event once per report, and the key leaves the recap out; S1 and S3-H both count it
  as two more captures.
- **Example.** `rumod-2026-07-29`, characters 3736 to 3811
  (https://t.me/mod_russia/66094): details of the capture of two villages, one in
  Donetsk and one in Kharkiv oblast.
- **Cause.** The extractor sees each post on its own terms and has no rule against a
  recap.
- **Fix.** State the repeat rule in the extraction prompt for RUMOD, with this post as
  the worked example; in the ledger, rule 7a already merges same-place repeats within 3
  days.

### 9. Directions and oblasts geocoded as places (AF and RUMOD)

- **What happens.** "On the Kramatorsk and Krasnyi Lyman directions" is a sector, not
  a place, but the key and the systems alike put it on Kramatorsk city, and S1 once
  wrote both directions as one place, which geocodes to nothing. In AF reports, oblast names in
  the regional form are matched to a village or to an OSM node of the same spelling:
  "Kyiv region" lands on a village called Kyryivshchyna, and "Sumy region" on an
  unlinked node named Sumska.
- **Example.** `af-2026-07-30`, characters 301 to 353 and 367 to 490
  (https://armyinform.com.ua/2026/07/30/osnovnyj-napryamok-udaru-%e2%80%94-kyyivshhyna-ta-lvivshhyna-syly-oborony-perehopyly-55-vorozhyh-raket-ta-265-bpla/):
  the regions hit overnight, typed `other` and geocoded as places. 12 AF events are
  typed `other` this way.
- **Cause.** The geocoder's oblast words cover the General Staff's forms, not the
  regional nouns the Air Force uses; the extractor has no event type for "regions
  hit" and falls back to `other`.
- **Fix.** Add the regional nouns to the oblast list at precision 3 (oblast), and a
  guideline ruling that regions named as hit belong to the strike event, not to
  separate events. The key has the same kind of error: on RUMOD dev the port of
  Pivdennyi near Odesa is geocoded to an inland namesake.

These four were seen before the test runs and not fixed, so that the test scores
measure the system that was frozen.


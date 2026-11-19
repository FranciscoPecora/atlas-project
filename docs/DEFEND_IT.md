# Defend it: study sheet

PLAN section 13 says the project is finished when its author can answer these ten
questions without notes. These are model answers built from the project's own numbers,
to study from and then put away. Numbers are from the test split (12 reports, 621
events, scored once) unless marked dev.

## 1. Why store character offsets instead of quoting the text?

- **Licence and the project rule.** ISW does not permit republishing its text. The General Staff text is CC BY 4.0, but the project publishes no source text at all, so that both sources can be handled the same way.
- **Checkable and fixed.** An offset pair, the SHA-256 of the cleaned text and the URL identify the exact passage. Anyone can rebuild the text, check the hash, and read the same characters. A quote can be paraphrased or trimmed by accident; an offset into hashed text cannot drift without the hash failing.
- **Small.** The public release is 84 KB for 4,550 events.

## 2. Why does the model return a quote and not the offsets?

- Language models read tokens, not characters, so they count characters badly. Offsets they wrote would often be off by a few characters, and nothing would catch it.
- A quote can be checked. Code searches for it in the text: if it is there, the offsets are exact by construction; if it is not, the record is rejected (S2 rejected 4 of S1's 586 test events for this).
- This is the hard rule: the model never produces offsets or coordinates.

## 3. Why match at 10 km and 1 day, and how does F1 move at 5 or 25 km?

- **10 km:** neighbouring front-line villages are a few kilometres apart, so 10 km tolerates the same place geocoded to a slightly different point without merging different places. **1 day:** reports describe "the past day", so the event date is usually the report date minus one, give or take a day.
- **Sensitivity (test):** almost flat. The day window changes nothing. At 25 km, B1 gains 0.002 and S3-H gains 0.015 (0.891 to 0.906). At 5 km, S3-H loses 0.002. The S3 gain at 25 km comes from the previous-day geocoding rule placing some events 10 to 25 km from where the key put them.

## 4. What does the verifier cost in recall, and is it worth it for an intelligence product?

- **Cost:** from S2 to S3-H, recall fell from 0.915 to 0.847 and F1 from 0.951 to 0.891. Precision fell as well (0.990 to 0.939), mostly because of the geocoder, not the verifier: false alarms rose from 6 to 34.
- **What it bought:** the unsupported-field rate fell from 4.04% (S2) to 1.43% (S3-H) in a 200-record dev-period audit. Its real value is dropping whole records whose quote is a bare place name.
- **Is it worth it:** on General Staff text, no. The text is formulaic and the model rarely invents anything. In an intelligence product, a confident false record can cost more than a missed one, so a verifier may pay off on varied prose like ISW, but that is untested. The honest position is to measure the trade on each source rather than assume it.

## 5. Why two linking rules, and what went wrong with one?

- **7a (duplicates)** groups reports of the same event: same type, within 5 km and 3 days, from any source, so events aren't counted twice. **7b (confirmation)** pairs a claim with a later geolocated confirmation at the same place and actor, within 30 days, to measure how fast claims are confirmed.
- **What went wrong (7a):** single linkage chains. A village named in most daily reports links day to day into one cluster, so the longest cluster spans 82 days and the widest is 22.5 km across. That is one long chain, not one event. The rule is fixed in SPEC, so it was reported, not changed.
- **7b** found 0 eligible claims: the General Staff never reports Russian claims or geolocated advances.

## 6. Why collect 120 days to analyse 90?

- A claim made on the last day of the corpus has had no time to be confirmed. Counting it as unconfirmed would bias the confirmed share downwards; this is right-censoring.
- So claims come only from the first 90 days (19 July to 16 October), and the last 30 days exist only to observe confirmations. Every claim gets the full 30-day window.

## 7. Where does the extractor fail on General Staff text that it handles in ISW text, and why?

- **Cannot be answered from evidence yet:** no ISW text was collected (permission pending), so the comparison was never run. Say so plainly.
- What is known on General Staff text (FAILURES.md): quotes cut down to a bare place name (on 23 July, 53 records lost their event type); "activity in the areas of" typed as `other`; villages sharing a name with others put at the wrong one.
- **Expectation, not result:** ISW writes full English sentences with the claim source named, so bare-name quotes should be rarer and the speaker easier to identify. ISW's harder parts would be nested attribution ("Russian milbloggers claimed...") and assessments mixed with facts.

## 8. Why not fine-tune a small model on your ~700 events?

- **Too little data, and the wrong data:** about 800 key events in total (175 dev, 621 test), and the test events may never be trained on. That leaves 175 events from 3 reports.
- **No headroom:** a single prompt already scores 0.962 F1. The remaining errors are geocoding and attribution, which fine-tuning a text model does not fix.
- **Cost and upkeep:** prompting costs under 2 US cents per report, and a fine-tuned model must be retrained when the schema or the source changes. Fine-tuning would pay off only with thousands of labels and a stable task.

## 9. You are the only annotator. What does that do to your F1?

- **No inter-annotator agreement,** so there is no ceiling to compare F1 with. The closest proxy: the annotator's own hand-labelling pass against the key matched at F1 0.972 (dev). That is self-consistency, not agreement between people.
- **The key is machine-made** (SPEC amendment A1): drafted by a model, audited by sample (1 of 28 test events judged wrong). It is from the same model family as the systems, so shared mistakes count as correct, and the scores are probably somewhat high.
- **The annotator reads no Ukrainian** and worked from a machine translation, so the audit cannot catch translation errors.

## 10. Why is B2 run on the same model as S1?

- So that the table isolates the method. B2 (one free-form prompt) and S1 (schema-constrained output) differ only in how the model is asked, not which model. Any F1 difference comes from the schema and the verification layers, not from a stronger model.
- The result: B2 0.962, S1 0.956, S3-H 0.891. On this source the method added nothing, and that finding is only valid because the model was held fixed.

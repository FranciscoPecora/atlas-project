# Claimline annotation guideline

Version 0.1, draft of 16 November 2026. Revised once after the 5-section pilot (version 1.0). SPEC.md wins if this guideline disagrees with it.

## 1. What you label

You label **events** inside the sampled units listed in SPEC.md section 4.2: two sectors per ISW report, or a whole General Staff (GSU) report. Text outside the sampled unit is not labelled, even if it describes the same event.

Each label is a span: the **evidence quote**, the shortest contiguous stretch of text that supports every field of the event. Then fill the attributes.

**One event per place per day.** "Russian forces attacked near A, B and C on November 14 and 15" is six events. Draw the same span six times, once per place-date pair. A sentence with no place is one event per day with no location. A sentence with no date takes the default date (ISW: the report date; GSU 08:00 report: the day before the report date).

**Not events:** forecasts ("Russian forces will likely attack"), intentions and objectives ("Russian objective: ..."), general assessments with no place or date ("Russian forces continue to struggle"), casualty totals for the whole war, political statements, and repeats of an event from an earlier day presented as background ("Russian forces seized X on November 3" in a November 15 report is labelled only if the report presents it as new information, for example new footage).

## 2. Event types

| Type | Use when | Example wording |
| --- | --- | --- |
| `ground_assault` | Offensive ground action at a place, successful or not | "attacked near", "conducted offensive operations", "assaults", "штурмові дії", "атакував" |
| `territorial_advance` | A side gained ground or seized a place | "advanced", "seized", "captured", "took control", "просунувся" |
| `withdrawal` | A side left positions or a place | "withdrew", "retreated", "відійшли" |
| `missile_strike` | Ballistic or cruise missiles hit or were launched at a target | "Iskander", "Kalibr", "ракетний удар" |
| `drone_strike` | Strike drones (Shahed, FPV, Lancet, long-range UAV) hit a target | "drone strike", "Shahed", "удар БПЛА" |
| `air_strike` | Manned aircraft or glide bombs (KAB) struck | "glide bomb", "airstrike", "КАБ", "авіаудар" |
| `shelling` | Artillery, MLRS or mortar fire | "shelled", "artillery strikes", "обстріл" |
| `air_defence_interception` | Air defence shot down missiles or drones | "shot down", "intercepted", "збито", "знешкоджено" |
| `force_movement` | Redeployment, build-up or rotation of forces | "redeployed", "concentrating", "rotated" |
| `logistics_or_infrastructure_strike` | A strike whose target is a depot, refinery, bridge, rail node, energy site, airfield, port. Overrides missile, drone and air types when the target is of this kind. | "struck an oil depot", "уражено НПЗ" |
| `naval_event` | Action at sea or against vessels | "struck a tanker", "naval drone" |
| `other` | A dated, placed military event that fits none of the above (sabotage, partisans, mines) | |

Rules for ties:
- A strike on a logistics or infrastructure target is `logistics_or_infrastructure_strike`, whatever the weapon. Record the weapon in `equipment`.
- An attack that gained ground is two events: `ground_assault` and `territorial_advance`, only if the text states both.
- Interceptions are one event per place per day, with `quantity` = number shot down when stated.

## 3. Epistemic status

Status follows the wording, not your judgement of whether it is true.

| Status | Trigger wording | Notes |
| --- | --- | --- |
| `ru_claimed` | "Russian MoD claimed", "Russian milbloggers claimed", "Russian sources claimed", "a Russian war correspondent stated" | Fill `claim_source` with the claimant as named |
| `ua_claimed` | "Ukrainian General Staff reported", "Ukrainian forces stated", "the commander of a Ukrainian brigade said". All GSU report text is `ua_claimed` with `claim_source` = "Ukrainian General Staff" unless it quotes someone else. | |
| `third_party_claimed` | Third governments, international bodies, media reporting on their own account ("Reuters reported") | |
| `geolocated_confirmed` | "Geolocated footage published on [date] indicates", "geolocated imagery shows", "ISW has observed confirmation" | The event is what the footage shows |
| `analyst_assessed` | "ISW assesses", "Russian forces likely", "indicating that", ISW's own unattributed statements of fact | Default for ISW narrative with no attribution |

Rules:
- When one sentence holds a claim and a confirmation of it, label two events with the same place and date and different statuses.
- "Russian milbloggers claimed X, but ISW has not observed confirmation" is `ru_claimed`. The doubt does not change the status.
- If ISW says "ISW assesses that Russian forces seized X" based on a claim and footage, it is `analyst_assessed`.

## 4. Actor and target

`actor` is the side acting (RU, UA, other). `target` is the side acted upon. Use null when the text does not say. Put the wording in `actor_text` / `target_text` when it names more than the side ("Russian VDV elements", "Ukrainian air defence").

## 5. Location and geo precision

`location_text` is copied exactly from the quote, in the case and inflection the text uses ("Pokrovsk", "Покровського", "near Kupyansk" gives "Kupyansk").

| Precision | Use when | Geocoded to |
| --- | --- | --- |
| 1 | A named settlement, landmark or point is where the event happened ("in Myrnohrad", "seized Bilytske") | That point |
| 2 | Relative to a settlement or a named direction or area: "near", "toward", "in the direction of", "northwest of", "on the outskirts of", "the Pokrovsk direction", "in the Lyman area" | The named settlement's point |
| 3 | Only an oblast or a whole front is named | Oblast centroid |

Several places in one sentence give one event each. "Between A and B" is precision 2, located at A, and a hard case to record.

## 6. Dates

`event_date` is the day the event happened, resolved from the text against the report date. "On November 14 and 15" gives two events. "Recently", "in recent days", "on an unspecified date" use the default date and are noted as hard cases. Footage "published on November 13" without an event date: use the publication date.

## 7. Units, equipment, quantity

- `units`: each unit named in the quote, written as in the text ("1st Guards Tank Army's 2nd Motorized Rifle Division"). Fill echelon and branch only if the text states them.
- `equipment`: weapon or vehicle names as written ("Shahed", "Iskander-M", "FPV drones", "КАБ").
- `quantity`: one integer stated in the quote that counts the event's main object (drones launched or shot down, missiles, assaults, combat clashes). Leave null if no number, or if the number is a range or an estimate ("over 100" is null; record as a hard case).

## 8. Procedure

1. Read the whole unit once before labelling. For a General Staff dev unit, read the English reading aid on the right: each paragraph `[n]` starts with the first Ukrainian words of paragraph n on the left. Select evidence on the Ukrainian side only, and copy place names from it (Cmd+C, Cmd+V) into `location_text`. The aid is machine translation: if it seems to contradict the numbers or names in the Ukrainian, the Ukrainian wins; note the case in section 9.
2. Label events in text order. Draw the shortest span that supports all fields.
3. Enter the minutes spent on the unit in the **Minutes** field at the bottom of the task, and set **Annotation pass** to 1 (2 only for the later consistency re-label).
4. Never label a test unit after seeing any model output for that report.
5. When unsure, label your best reading and add the sentence to section 9.

## 9. Hard cases

Fill after the pilot. For each: the sentence (paraphrased, no long quotes), the ruling, and the reason.

| # | Case | Ruling | Reason |
| --- | --- | --- | --- |
| 1 | "Continued attacks" with no date | | |
| 2 | "Unspecified positions" with no place | | |
| 3 | A claim ISW reports and doubts in the same sentence | `ru_claimed` (see 3) | Status follows wording |
| 4 | An advance "northwest of" a town | Precision 2 at the town (see 5) | |
| 5 | "Between A and B" | | |
| 6 | Numbers given as "over", "about", "up to" | | |
| 7 | GSU daily totals per direction ("X combat clashes on the Pokrovsk direction") | | |
| 8 | Footage published today showing an event of unknown date | | |
| 9 | | | |
| 10 | | | |
| 11 | | | |
| 12 | | | |
| 13 | | | |
| 14 | | | |
| 15 | | | |

## 10. Pilot log

| Date | Unit | Events | Minutes | Changes made to this guideline |
| --- | --- | --- | --- | --- |
| | | | | |

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

### 8.1 Pre-filled General Staff dev tasks

> Since 17 November 2026 the checking described below is done by a reviewer model (`src/review.py`), and you only spot-check a random sample in English (`src/audit.py`, section 8.2). The steps below remain the rules the reviewer follows, and the fallback if the spot check fails.

Dev GSU tasks open with events already drawn by `src/prelabel.py` (rules, no model). They are proposals. Your job per task:

1. **Control first.** The task with sector `CONTROL` (two paragraphs of the 6 August report) has no pre-fill. Label it from scratch before opening any pre-filled task. It measures whether the pre-fill steers you (`uv run python -m src.prelabel_check`).
2. **Check every pre-filled event** in the region list on the left: right place, right type, right date. Fix wrong fields, delete wrong events (select, Backspace), and add events the rules missed.
3. **What the rules cannot see,** so look for it yourself:
   - front-wide totals and Ukrainian strikes with no place (the 2 to 3 paragraphs after the "8:00" line): decide per hard case 7, and add a row to section 9 for strikes with no place;
   - the type: every place event is pre-filled as `ground_assault`; change it if the sentence says shelling, an air strike or an advance;
   - two events at one place on one day (an assault and an advance): the rules make one.
4. **Pre-fill conventions** (keep or overrule them, then record the ruling in section 9):
   - a count shared by several places ("attacked 14 times towards A, B and C") gives no `quantity`; a count with a single place does;
   - a paragraph with no settlement but a named direction gives one event per kind (clash, air strike, shelling) located at the direction, precision 2;
   - all place events are precision 2 ("in the area of", "towards").
5. Submit as usual: Minutes, Pass 1, Submit.

### 8.2 Spot check of the machine-made General Staff key

1. Open `data/audit/audit.html` (double-click it in Finder). It shows 30 random events and 10 random paragraphs, in English.
2. Event: **Right** if the paragraph says this kind of event happened at this place (and the count, if shown, is in the paragraph for that event). Otherwise **Wrong**, with a short note. An empty count is correct when the paragraph's number is a total for several places (hard case 9); it is never a reason for Wrong or Something missing.
3. Paragraph: **Complete** if every event and every attacked village has a box. Otherwise **Something missing**, with a note saying what.
4. **Not sure** is a valid answer. Do not guess.
5. Click **Save answers** at the end. The key is accepted if at most 5% of judged events are wrong and at most 5% of judged paragraphs miss something (config `audit.max_error_rate`).

### 8.3 Hand labelling of General Staff dev units from the translation

`make handlabel` opens a local page that shows one paragraph at a time in English. Nothing is pre-filled and the machine-made key is not shown. For each event the annotator picks the type, clicks every place it happened at (one event per place) and, when a number counts that one event, types the count. Code fills in the place name as written in Ukrainian, the evidence offsets (the sentence that holds the place, or the whole paragraph when no place is clicked), the date, `ua_claimed` and precision 2. The place buttons come from the translation's list of place names. The page logs minutes per unit. The result is saved to `eval/human/dev/` and is compared with the machine-made key; it does not replace the key.

### 8.4 Air Force and Russian MoD reports (SPEC amendment A2)

Written on 2026-11-19, before any AF or RUMOD text was labelled. Every rule above
applies; these add what the two sources need.

**Air Force (AF), one overnight air-attack report.** All of it is `ua_claimed` with
`claim_source` = "Ukrainian Air Force".

- The attack: "the enemy attacked with N strike drones" is one `drone_strike` (actor RU,
  target UA, `quantity` N). Each missile kind with its own count ("2 Iskander-M
  ballistic missiles", "Kh-101 cruise missiles") is one `missile_strike` with that count
  and the kind in `equipment`. Decoy drones counted separately are not strike events.
- The defence: "air defence shot down or suppressed N" is one `air_defence_interception`
  (actor UA, target RU, `quantity` N). When the text splits it ("N drones and M
  missiles"), one event per kind.
- Places: launch areas ("from the directions of Bryansk, Kursk") are not event places
  and give no event. Regions of hits or of interceptions are places only when an oblast
  or settlement is named (precision 3 for an oblast). "North, south and east of the
  country" is no place.
- Hits: "hits of N drones at K locations" with no place is not an extra event (it is
  part of the attack already counted). A hit with a named oblast or city is one
  `drone_strike` or `missile_strike` there, with no `quantity` unless one is stated
  for that place.
- Date: the night's date as written ("the night of 3 August" is 3 August), else the
  report date.
- Evidence: the attack and the defence are stated more than once (headline, first
  sentence, a longer quote). Label each once per report, quoting the body sentence that
  states it, not the headline. (Added 2026-11-22, after the dev spot check, before any
  test key.)

**Russian MoD (RUMOD), one day of channel posts.** All of it is `ru_claimed` with
`claim_source` = "Russian Ministry of Defence". Each post starts with a `## <url>` line;
that line is never part of a quote.

- Captures: "units of group X liberated (took control of) the settlement Y" is one
  `territorial_advance`, actor RU, target UA, precision 1 at Y, `location_text` = Y as
  written. The oblast or "DNR"/"LNR" named after it decides between namesakes.
- Air defence: "air defence intercepted and destroyed N Ukrainian drones" is one
  `air_defence_interception`, actor RU, target UA, `quantity` N. Regions of Russia are
  outside the gazetteer: give no `location_text` when the count is for several regions
  together; when a count is given per region, one event per region with
  `location_text` as written and precision 3.
- Strikes: "a massed strike was made on defence-industry and energy sites" is one
  `logistics_or_infrastructure_strike` (actor RU, target UA), weapons in `equipment`, no
  place unless one is named. Strikes on "temporary deployment points" or "manpower and
  equipment in N areas" follow hard case 11 (one `other` event with the count).
- Repeats: the evening digest ("The main points of the day") repeats claims made in
  earlier posts the same day. Label each claim once per report, at its first mention.
- Losses ("the enemy lost up to 200 servicemen", vehicles destroyed with no place) are
  not events (hard case 10).
- Date: a time window in the text ("from 20:00 on 7 July to 08:00 on 8 July") gives the
  date it ends; otherwise the report date.

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
| 7 | GSU daily totals per direction ("X combat clashes on the Pokrovsk direction") | If the paragraph names settlements: one event per settlement and no event for the total. If it names none: one event per kind (clashes = `ground_assault`, air strikes, shelling) located at the direction, precision 2, with the count as `quantity`. Provisional, 17 Nov 2026 | The total and the settlements describe the same fighting; counting both would double it |
| 8 | Footage published today showing an event of unknown date | | |
| 9 | A count shared by several places ("attacked 14 times towards A, B and C") | No `quantity` on any of them. A count with a single place is that place's `quantity`. Provisional | The share per place is unknown |
| 10 | Front-wide totals with no place and no direction ("261 clashes over the past day", "60 air strikes", losses of personnel and equipment) | Not an event | No location to match on; it restates the per-direction paragraphs |
| 11 | Ukrainian strikes on "areas of concentration" or "command posts" with a count but no place | One event per kind of target struck, type `other` when aviation, missiles and artillery are named together, actor UA, target RU, no location, with the count. Confirmed by the owner, 17 Nov 2026 | It is a distinct claimed event; it stays unmatched on location by design |
| 12 | "In the area of", "towards", "near" a settlement | Precision 2 at the settlement (see 5). One event per settlement per paragraph per type | Same as hard case 4 |
| 13 | A paragraph that opens with two directions and names no settlement ("On the North Slobozhanskyi and Kursk directions there was one clash, three air strikes, 66 shellings") | One event per kind for the two directions together: `location_text` is both directions as written, precision 2, with the count as `quantity`. Not one event per direction. Confirmed by the owner, 18 Nov 2026 | The count is stated for the pair. One event per direction would either lose the count (case 9) or count the same fighting twice |
| 14 | AF: a total of hits "at K locations" with no place | Not an event; the attack event already counts the drones. Provisional, 19 Nov 2026 (A2) | Counting it would count the same drones twice |
| 15 | RUMOD: the evening digest repeats the day's earlier capture and interception posts | One event per claim per report, at its first mention. Provisional, 19 Nov 2026 (A2) | The digest restates; it is not a second claim |
| 16 | RUMOD: interceptions over several Russian regions with one total | One event with the total and no place. Provisional, 19 Nov 2026 (A2) | Splitting would lose the count (case 9); the regions are outside the gazetteer |
| 17 | AF: launch areas named ("from Bryansk, Kursk, Crimea") | Not event places, no event. Provisional, 19 Nov 2026 (A2) | They say where the attack came from, not where it happened |

## 10. Pilot log

| Date | Unit | Events | Minutes | Changes made to this guideline |
| --- | --- | --- | --- | --- |
| 2026-11-17 | gsu-2026-07-21 FULL | 59 | machine-made (A1) | Hard cases 7, 9 to 12 ruled; section 8.2 added |
| 2026-11-17 | gsu-2026-07-29 FULL | 66 | machine-made (A1) | |
| 2026-11-17 | gsu-2026-08-06 FULL | 56 | machine-made (A1) | |
| 2026-11-17 | Spot check round 2 (30 events, 10 paragraphs) | 40 items | not logged | Count rule stated in 8.2 after void round 1 |
| 2026-11-18 | Dev key, hard case 13 (21 July paragraph 6, 6 August paragraph 4) | 181 to 175 | src/keyfix.py | Hard case 13 ruled: two directions, one event per kind with the count |

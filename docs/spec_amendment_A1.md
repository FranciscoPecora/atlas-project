# Amendment A1: machine-made answer key for General Staff reports

Status: **approved by Francisco Pecora on 2026-11-17** and recorded in SPEC.md, Amendments.
In code the method still runs on dev reports only; test reports are enabled in milestone 2 (see DECISIONS.md).

## Why

The annotator cannot read Ukrainian and labelling 15 full General Staff (GSU) reports by
hand is not feasible. GSU reports follow one fixed sentence pattern, so most events can be
found by rules.

## What changes

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

## Not changed

ISW units (still labelled by hand, in English), metric definitions and targets other than
the consistency row, the dev/test split, and the rule that test gold files are opened only
by `eval/score.py`.

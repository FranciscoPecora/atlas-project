---
name: quiz
description: Quiz the user on what was just built. Run after every milestone.
disable-model-invocation: true
---
Look at the commits since the last tag or the last quiz entry in DECISIONS.md.
Ask me three questions about the mechanism of what we just built: why it works,
what would break it, and what the alternative was. One question at a time.
Wait for my answer before the next one.
Correct me bluntly and specifically. Do not soften wrong answers.
If I get one wrong, explain it, then ask a second question on the same mechanism.
When I have answered all three correctly without help, append a dated line to
DECISIONS.md for each decision we discussed (decision, reason, alternative rejected).
Do not start the next milestone until this is done.

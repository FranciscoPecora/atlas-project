---
name: milestone
description: Close out a milestone. Lint, test, record results, commit.
disable-model-invocation: true
---
1. Run `make lint` and `make test`. Fix failures before going on.
2. If this milestone produced dev-set or validation numbers, append them to
   eval/results.csv with the commit hash, the config values used and today's date.
3. Check the "Done when" list for the current milestone in PLAN.md. List each
   item as done or not done. Do not mark anything done that you have not verified
   by running it.
4. Update README.md only if a result or a limit changed.
5. Commit with a message that starts with the milestone number.
6. Tell me what is left, what you were unsure about, and any place where you
   departed from SPEC.md. Then stop and tell me to run /quiz.

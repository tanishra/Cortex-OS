# Benchmark Results — Online-Mind2Web easy × 3 models

*Dated 2026-10-20. 15 easy tasks per model, concurrency 2, caps 30 steps / 240s. Self-hosted headless Chromium on a laptop. Verdicts: auto (done + non-empty result = pass) — optimistic, manually spot-checked.*

## Headline table

| model | n | done | rate | avg steps | avg time (s) | $/task | $ total |
|---|---|---|---|---|---|---|---|
| gpt-5-mini | 15 | 4 | 26.7% | 14.6 | 181.6 | $0.024 | $0.354 |
| gpt-5-nano | 15 | 4 | 26.7% | 18.2 | 189.2 | $0.005 | $0.076 |
| gpt-5 ⚠️ | 15 | 1 | 6.7%* | 3.9 | 100.4 | $0.008 | $0.126 |

⚠️ **gpt-5's number is tainted, not a real comparison.** OpenAI credits hit `credit_balance_exhausted` mid-run — most tasks died at 2–5 steps on 429s, not on real failures. Re-run needed after adding credits.

## What the clean data says

**gpt-5-nano matches gpt-5-mini on success at ~5× lower cost.** Same 4/15 pass rate. This is the interesting finding: for browse-and-extract tasks, a cheaper model does the job — the bottleneck is the websites, not the brain.

The two models even failed *differently*: nano looped on tools (`tool_loop`) twice while mini's failures were mostly timeouts.

## Failure categories (45 tasks)

| category | mini | nano | gpt-5 | meaning |
|---|---|---|---|---|
| success | 4 | 4 | 1 | finished with an answer |
| timeout_on_site | 5 | 3 | 9 | still working when the cap hit |
| wandered_domain | 3 | 3 | 2 | left the task site for alternate sites |
| wandered_offsite | 1 | 0 | 0 | fled to a search engine |
| bot_blocked | 1 | 2 | 2 | captcha / DataDome / human wall |
| tool_loop | 0 | 2 | 1 | repeated same action ≥5× |
| failed_other | 1 | 1 | 0 | other errors |

**~2/3 of all tasks end in some failure mode — consistent with the published ~30% figure for self-hosted browser agents.** Sites that blocked us outright: Qatar Airways, SeatGeek (DataDome), AdoptAPet (CloudFront 403), Eventbrite.

## Honest caveats

- n=15 per model is a *pilot* sample — direction, not proof. Scale to 50+ before publishing strong claims.
- `autojudge` counts `done` + non-empty result as pass — agent can falsely claim success; spot-check passes before quoting numbers.
- "easy" level only — harder tasks will score lower.
- Self-hosted Chromium gets bot-blocked where managed browsers (Stealth/Cloud) might not.
- gpt-5 must be re-run after OpenAI credits are topped up.

## Cost observation

Total spend for 45 tasks: **$0.56**. The expensive models didn't win — the websites won. A 300-task × 3-model full benchmark is affordable (~$5–10 on these models), just slow.

## Files

- `evals/benchmark/easy15_gpt-5-mini.json`, `easy15_gpt-5-nano.json`, `easy15_gpt-5.json` — committed reports
- `docs/failure-analysis.md` — taxonomy + earlier 5-task deep-dive
- Reproduce: `python -m evals.bench --level easy --limit 15 --model <model> --concurrency 2 --timeout 240`

# Failure Analysis — Online-Mind2Web easy pilot (5 tasks)

*Dated 2026-10-20. Two runs: `baseline_easy5.json` (before prompt fix) and `postfix_easy5.json` (after). Model: gpt-5-mini. Caps: 30 steps / 240s per task.*

## Taxonomy (auto-classified by `evals.bench`)

| Category | Meaning | How detected |
|---|---|---|
| `success` | Task finished and produced an answer | status == done |
| `bot_blocked` | Site rejected us (captcha / wall fired) | `waiting_human` status event |
| `wandered_offsite` | Agent gave up on the site and fled to a search engine | step URL on google/bing/ddg/yahoo/baidu |
| `timeout_on_site` | Still working on the right site when the cap hit | error = bench_timeout, no flee |
| `failed_other` | Everything else (errors, early exits) | fallback |

## Run 1 — baseline (before fix)

| Task | Site | Status | Steps | Category | What happened |
|---|---|---|---|---|---|
| MacBook specs | apple.com | fail | 19 | timeout_on_site | Reached the right specs page but ran out of time before answering |
| MLS standings | foxsports.com | pass | 21 | success | Extracted real standings; 426k input tokens |
| Brooklyn maps | new.mta.info | fail | 28 | wandered_offsite | Site search beaten → fled to Bing, re-searched 25+ times |
| Popular TV | rottentomatoes.com | fail | 20 | timeout_on_site | Reached the right page; "Load more" element indices kept shifting |
| Shelter search | adoptapet.com | fail | 2 | bot_blocked | CloudFront 403 → fled to DuckDuckGo → captcha wall → paused |

**Score: 1/5. Dominant pattern: the agent doesn't know when to quit — it wanders off-site burning tokens.**

## The fix (P6c)

Added two lines to `SAFETY_EXTENSION` (system prompt): stay on the task's website, no search engines, report blocks plainly and stop. Prompt-level only — no hard block, since some tasks legitimately need navigation freedom.

## Run 2 — post-fix

| Task | Site | Status | Steps | Cost | Category | What happened |
|---|---|---|---|---|---|---|
| MacBook specs | apple.com | **pass** | 9 | $0.042 | success | Clean path: Mac → Learn more → Tech Specs → extract. 19→9 steps, failed→done |
| MLS standings | foxsports.com | fail | 21 | — | timeout_on_site | Reached the data (30 `tbl-row-*` rows visible in memory) but looped on `find_elements` instead of extracting — a tool-usage loop |
| Brooklyn maps | new.mta.info | fail | 3 | $0.006 | failed_other | **Model failure.** Site returned "Access Denied" (Akamai edge) — agent reported it honestly and stopped. Fast, cheap, truthful: the *right* kind of fail |
| Popular TV | rottentomatoes.com | fail | 20 | — | timeout_on_site | Better path (dismissed cookie banner, found "View all") but hit LLM output-truncation + loops → timeout |
| Shelter search | adoptapet.com | fail | 21 | — | timeout_on_site | **Prompt bypass.** 403'd → didn't flee to a *search engine* (prompt worked literally) — fled to *alternative directories* (Petfinder, Petango, PetPlace) instead |

## Before / after

| Metric | Before | After |
|---|---|---|
| Success rate | 1/5 | 1/5 |
| `wandered_offsite` (to search engines) | 2 tasks | 0 tasks |
| Cheapest honest fail | 28 steps wandering | 3 steps + honest report ($0.006) |
| Tokens burned (total in) | 426k | 169k |
| Cost measured | $0.00 (cost tracking was off — bug found + fixed) | $0.0476 total |

## Findings (ranked)

1. **Prompt discipline works, partially.** Search-engine fleeing stopped; MTA failed in 3 steps with an honest "Access Denied" report instead of 28 steps of wandering. Apple went 19-step-timeout → 9-step success.
2. **The agent interprets rules literally.** "No search engines" → it fled to *competitor sites* (Petfinder/Petango). Tightening the rule to "no other websites" would help — but honestly, the adoptapet 403 was unwinnable anyway; the wandering just wastes budget. Next fix: broaden rule or add `left_original_domain` category.
3. **Tool-usage loops are the new top failure.** foxsports had the data in memory and kept re-running `find_elements` (browser_use loop-detection nudged 9×). That's a browser_use-level issue, not ours — but our timeout + cost guard contain the damage. Documented as `tool_loop` pattern; classifier could detect "same action ≥5× consecutively" → `tool_loop`.
4. **`Model output was truncated at max_completion_tokens=4096`** appears repeatedly — worth raising `max_completion_tokens` on the LLM or retrying with shorter-output instruction (candidate fix #2).
5. **Two more categories needed:** `tool_loop` (same action repeated) and `wandered_domain` (left the site for non-search domains). Add to classifier when scaling.

## What this tells us for scaling (P6b)

- Cost per task now measurable: ~$0.01–0.05 on easy tasks, dominated by wandering. A 50-task run ≈ $0.50–2.50 + ~2–3h sequential — cheaper than feared.
- Timeout (240s) is doing its job converting infinite wandering into bounded failures.
- Success rate will stay ~20–40% on live sites — expected and honest; the value is in the failure taxonomy and measured improvements.

## Next candidate fixes (by expected impact)

1. Raise `max_completion_tokens` (or set a model default) — truncation appeared in 2/5 tasks.
2. `tool_loop` detection → stop the agent after N identical actions.
3. Broaden stay-on-site to cover "no off-site navigation except to continue the same task" OR accept it and classify `wandered_domain`.
4. Larger sample (30 easy tasks) to confirm category distribution.

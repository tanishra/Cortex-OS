# DESIGN.md — Cortex-OS UI

## World — Flight Recorder

The replay viewer *is* a black-box: the system records every step an agent took and this surface plays it back. Visual identity = flight data recorder / instrument panel: dark ground, amber telemetry, engraved labels, indicator-lamp status, a recording track as the timeline.

## Palette — Restrained + committed accent

- `--bg`: #0B0D10 (instrument housing, near-black warm)
- `--panel`: #13161B (engraved plate)
- `--panel-2`: #1A1E24 (raised plate)
- `--line`: #262B33 (hairlines, not borders)
- `--ink`: #D8DBDE (primary text)
- `--ink-dim`: #8A9099 (secondary/engraved)
- `--amber`: #F5A623 (telemetry accent — active state, key values, the record rail)
- `--green`: #3FB27F (done/pass/held)
- `--red`: #E0564F (failed/error)
- `--blue`: #5B9BD5 (queued/running pulse)
- `--warn`: #E0B84F (waiting_human/waiting_approval — lamp lit)

## Type 

- UI face: system stack (`-apple-system, "Inter", "Segoe UI", sans-serif`)
- Data/mono face: `ui-monospace, "JetBrains Mono", "SF Mono", Menlo, monospace` — all numerals, timestamps, IDs, URLs in mono
- **Rank rule (timetable raise):** two sizes only — 13px body + 11px labels. Hierarchy via weight/case/color/tracking: labels are `uppercase`, `letter-spacing: .08em`, `ink-dim`; values are weight 600 or mono `amber`/`ink`. No display sizes, ever.

## Components

- **Status chip:** engraved lamp — 8px dot + uppercase mono label; colors above; running pulses at 1.4s
- **Task rail item:** one-line task + status chip + mono time-ago; active row gets left amber tick, not a fill
- **Step card:** hairline plate; header = `n` + URL mono + duration; body = actions mono list; screenshot thumb right, 96px, 2px line frame; click → lightbox
- **Approvals lamp strip:** warn-colored row, approve (green ghost) / deny (red ghost) buttons — one element per screen goes reversed (the primary CTA fill)
- **Controls:** ghost buttons, hairline border, 11px uppercase; primary action filled amber on dark
- **Empty states:** "no tasks recorded" with recorder-stamp style (mono, dim)

## Layout

Fixed-height shell: 56px top bar (wordmark `CORTEX-OS` mono + "REC" lamp + key-entry button + submit) → 280px task rail (scrollable) | detail pane. Detail pane header = task metadata band (status chip, task text, site, tokens/cost/duration in mono row), below: approvals strip (if pending), then step timeline, event log toggle, result block.

## Motion / a11y

- 120ms ease hovers; running-lamp pulse the only continuous animation; `prefers-reduced-motion` kills pulse
- Status colors always paired with labels (never color-only); focus-visible 1px amber outline
- Screenshots lazy-loaded

## Bans

No gradients (except none), no purple/blue AI-slop palettes, no emojis in UI, no icons-as-decor, no rounded-pill-overload (6px radius max), no Inter-as-display, no third type size.

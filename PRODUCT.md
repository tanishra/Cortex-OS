# PRODUCT.md — Cortex-OS

**What:** Self-hosted service that runs AI browser agents — queue, safety rails, replay. The AI itself is browser-use + OpenAI; Cortex-OS is the operations layer around it.

**Audience:** the builder (portfolio/demo) + technical reviewers/interviewers who will judge the system by watching it work.

**This surface:** `/ui` replay viewer (Tier-1): task list, step timeline with screenshots, approvals inbox, cancel/resume, submit form. Mode: **Operate** — reviewers scan status and drill into a task's steps.

**Real scene:** dark office/laptop, reviewer skimming many tasks, wants "what happened?" in one glance and proof (screenshots) one click deep.

**Assumptions (user delegated direction):** ops-console aesthetic is the honest fit — the product IS an ops layer; a marketing-style surface would misrepresent it.

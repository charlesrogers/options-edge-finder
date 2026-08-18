# How-It-Works 10x Spec — the evidence page that earns a 30-year veteran's trust

**Executor:** Opus 5, fresh session, working dir `/Users/charlesrogers/Documents/options-tool`
**Sequencing:** runs AFTER `tasks/web-overhaul-spec.md` closes green (this page must be built on corrected data, never alongside stale data). Verify that first, per §0 discipline.
**Read first:** `tasks/lessons.md`, `ticker_strategies.py` (every note), `docs/dad-pitch.md`, `results/006_covered_call_copilot.md`, `results/022_*.md`, `results/023_*.md`, `docs/claims-inventory.md` (produced by the overhaul), house design language section of `~/.claude/CLAUDE.md`, `web/CLAUDE.md`

## §1 Who the page is for, and the one job it does

Primary reader: Charles's father — 30 years at Goldman/CS/DB, 10,000 shares per ticker, lost ~$400K once to a missed ex-dividend assignment on MSFT. He does not need options explained. He needs a reason to trust a tool with a $400K failure mode. Secondary readers: Charles, and anyone either of them shows it to.

The page's single job: **make the case that this system deserves trust, using only evidence that survives his scrutiny.** Not marketing. Methodology, data sources, and outputs — the evidence trail IS the pitch. If a sentence would embarrass us in front of a risk committee, it doesn't ship.

## §2 The narrative arc (section blueprint — content is specified, copy is the executor's craft)

1. **The $400K sentence.** Open with the problem in one line: an ITM covered call held through ex-dividend gets assigned, and at 10,000 shares that is a six-figure tax event. It happened once. The tool exists so it cannot happen again. (No melodrama — one paragraph, his own war story back at him.)
2. **The alert ladder, on the real data.** The five levels (SAFE → EMERGENCY) presented against the empirical assignment-probability table — 145,099 real option observations, moneyness × DTE. Render the table as an interactive heatmap (dataviz discipline: load the dataviz skill before building any chart). The reader should be able to find "3% OTM, 7 DTE" and see 15.8% — and understand exactly why CLOSE SOON fires there.
3. **The exit discipline: why we buy back early.** The core empirical finding: at every moneyness and every DTE, closing now beats waiting — with the tail numbers (99th-percentile savings $30–36/share at 14 DTE). One chart. Then the two rules that follow: never hold to expiry, no stop losses (whipsaw evidence, Exp 001→002 lineage honestly told: "our first version of this finding used fake prices; the real-price version killed half of it — here's what survived").
4. **The entry rules.** Per-ticker strikes and DTE from `ticker_strategies.py` (rendered from the same generated source as /sell — never hand-copied), the IV gate with the per-ticker trial result (DIS ≥75, Exp 023 — the only optimization that survived), the two calendar bans (earnings, ex-div). State plainly what we do NOT do: predict direction (H10: every predictor had zero weight; base rates near coin-flip), use leverage, sell naked anything.
5. **The process is the edge.** Pre-registration with immutable thresholds; walk-forward holdouts; the graveyard. Show the actual score: **N hypotheses registered, M failed, K deployed** — pulled LIVE from `signal_graveyard` via the API, not hardcoded. The sentence that lands with this reader: "Most of what we tested didn't work, and we can show you every failure." Include the two engine bugs we caught ourselves (the DTE clock bug that invalidated seven of our own experiments; the fabricated IV rank) and what each did to our published numbers — claims went DOWN when we found them. That is the trust asset; spend it.
6. **The reliability story: silence is impossible.** The three-layers diagram: chain 1 (server cron → assessment engine), chain 2 (GitHub Actions → Python engine), watchdogs (Hetzner health cron + Cloudflare worker on a different provider), heartbeats verified by read-back, market-calendar-aware freshness. Crown it with a **live status widget**: current monitor heartbeat age, last capture age, health state — the page itself proves the system is awake right now. (Read from the same health/heartbeat source of truth; show timestamps; the widget must itself display staleness honestly if the data is old — a live widget that lies defeats the page.)
7. **Honest expectations.** Income is a ~0.5–1% yield overlay; premium retention is deliberately sacrificed for zero assignments; per-ticker P&L shown as RANGES with the regime caveat (half-year swings −78%→+93%); bear-market validation status stated plainly (Monte Carlo done; real-price 2020/2022 test pending/complete — read current state from results/). The insurance-that-pays-you frame from dad-pitch.md.
8. **The daily workflow.** Two minutes in the morning, phone buzzes when it matters, "if the daily proof-of-life push doesn't arrive, assume the tool is dead." One screenshot-style walkthrough of an alert acknowledged.

## §3 Design directives

- House design language (global CLAUDE.md): Geist, OKLch tokens, shadcn/base-nova, px-based type scale, `max-w-7xl`. Dark mode first-class.
- Load the **dataviz skill before writing any chart code**. Charts: assignment heatmap (§2.2), close-now-vs-wait chart (§2.3), experiment timeline/graveyard scorecard (§2.5), three-layer reliability diagram (§2.6). Every chart carries its n and its source experiment inline.
- Prose density: this reader skims tables and reads footnotes. Short declarative sections; numbers in tables, not paragraphs; every claim footnoted to its results file (link into the repo or a /methodology anchor).
- No testimonials, no adjectives doing evidence's job, no "AI-powered" anywhere.

## §4 Process guardrails (the visual-work lessons, binding)

- **Iterative visual confirmation with Charles is mandatory.** Ship in 3 checkpoints: (1) content/IA draft as a static page — Charles approves structure; (2) charts + live widgets in — Charles approves visuals; (3) final polish. Do NOT build the whole page and reveal it once. Never claim visual quality from code inspection — screenshots at each checkpoint.
- Every number on the page passes the claims-inventory test (traceable or absent). The live widgets and graveyard counts are queries, not constants — a constant pretending to be live is the fossil bug again.
- `npx next build` before every push; deploy verified by polling production for new content; the §7-style acceptance from the overhaul spec applies: rendered-surface proof.

## §5 Acceptance

1. Charles has visually approved all three checkpoints (his sign-off in the session, not inferred).
2. Live production page renders: the interactive assignment table, the live status widget showing a fresh heartbeat, the graveyard scorecard with live counts, per-ticker rules identical to /sell's generated source, and zero claims outside the inventory.
3. The failure-disclosure section names the DTE bug and the fabricated IV rank with their before/after numbers.
4. A cold-read test: the executor writes the three questions a skeptical desk veteran would ask after reading, and the page must already answer all three on its face.

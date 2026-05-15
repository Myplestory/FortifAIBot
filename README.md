<img src="assets/fortifai_logo_minimal.png" alt="FortifAI" width="100%">

# FortifAI  
&nbsp;

> "for other self directed learners across the world. may knowledge always remain yours to reach for." 

&nbsp;

## What? Another LLM chatbot?

FortifAI is a Discord bot that quizzes you on technical knowledge and grades your answers against published, industry adopted competency frameworks instead of an LLM's improvised opinion. It writes scenario questions calibrated to a target skill band, probes the weakest point in your answer with one follow-up, then scores the exchange against all five bands and hands back a scoped reading list to where you actually are.

The bot is one interface. The grading pipeline underneath ([`phases/`](phases/)) has no Discord coupling and is built to be wrapped by any front end. Agnostic by design.

## Thesis

***The asymmetries on-demand LLM knowledge generates between laundered competency, foundational understanding, and distinguishing them are resolvable by the same capabilities that drive the widening gap. Information gating, citeable anchoring, and systemically constrained outputs enables discrepancies to be surfaced legibly for users and external observers alike***

FortifAI inverts typical LLM usage, leveraging the properties that fosters cognitive offloading to constrain it purely as a proctor, not an adjudicator. It writes band-calibrated questions, probes the highest-leverage ambiguity in the response, and scopes literature to the demonstrated level with estimated reading times. What gets tested and how it scores are fixed by published criteria before the model runs. 


**Grounded in published work:** the Dreyfus skill-acquisition model (Dreyfus & Dreyfus, 1980; rev. 2021), IEEE SWECOM (2014), SFIA v9 (2024), reference-guided LLM judging (Zheng et al., 2023, arXiv:2306.05685), degradation in LLM Multi Instance Processing (Chen et al., 2026, arXiv:2603.22608).

## Applications

- **Software engineering study companion.** Install, point a Discord bot at it, run `/knowledgeharden`. The shipped [`templates/swe/`](templates/swe/) covers 8 engineering fields graded against Dreyfus, SWECOM, and SFIA. Sessions are multi-user and persist across restarts, with a deduplicated reading list per session.
- **Other domains.** Author `templates/<domain>/` and update [`parse.CANONICAL_FIELDS`](parse.py) to your industry's taxonomy. Anything with cited band criteria works: security, ML research, clinical informatics, regulatory compliance. The pipeline picks up the new domain on the next run.
- **A pipeline you wrap.** [`phases/`](phases/) exposes pure functions with strict JSON validation. Build a CLI, web app, or Slack equivalent against the [public surface](#public-surface). Only [`commands/`](commands/) and [`main.py`](main.py) are Discord-specific.

> **FortifAI is a study and diagnostic tool. It does not certify competence, predict promotion or hiring outcomes, or replace accredited programs.** It surfaces technical competency through recall and reasoning under time pressure, which is the substrate mastery is built upon. It does **not measure mastery itself**, which takes years of work in a domain. Treat the output as a study companion, not a verdict. 
*Career estimations are analogous ranges that primary sources for industry promotion evaluations converge on, not a definitive claim.*

## Features

### `/knowledgeharden` quiz loop
Five scenario-based questions, one per field, calibrated to a target band (B1-B5). One refinement probe per question on the highest-leverage ambiguity. Grading is done against all five bands, with each question sandboxed. A final pass for coherence then generates two literature picks per question upon agreement. 
**Time bounded**: 10 minutes for the initial answer, 5 for the refinement. 
***Pressure surfaces genuine conceptual depth and fluency, discouraging cheap bypasses.***

### Sessions
`/sessionbegin`, `/sessionend`, `/sessionswitch`, `/sessionlist`, `/sessionrestore`. Multiple concurrent contexts per user, persisted across restarts. A deduplicated reading list is emitted when a session closes. `/sessionbegin` can set default `industry`, `fields`, `topics`, `domain`, and `stack`, inherited by runs that do not override them.

### Reference
`/bands` explains B1-B5 against Dreyfus, SWECOM, and SFIA, with a calibration verdict against your latest run. `/rubric` shows the framework citations and per-field SFIA scope. `/directory` lists industries, fields, and topics.

### Analytics
`/stats runcount|timeline|session` and `/analyze trends|gaps|bias`. Coverage, growth deltas, and field-rotation bias, rendered as embeds with inline charts.

### Transcript
`/transcript` dumps the full question set, grading, and literature for any past run.

### Reminders
`/schedule add|list|remove` sets recurring DM nudges to take a quiz, backed by APScheduler (sqlite).

### Sweep
`/sweep` reclaims abandoned runs, regrades failures or the latest run only, and heals the `meta.json` catalog (modes: `cleanup`, `regrade`, `regrade-last`, `catalog`, `all`).

### `/help`
Lists every command, grouped by category.

## Examples

A `/knowledgeharden` run ends with three embeds: a summary, a per-question breakdown, and a scoped reading list. Reference and analytics commands render inline charts.

<img src="assets/example/gradeaggregate.png" alt="Run summary" width="700">

<sub>**Run summary.** Settings, the unassisted aggregate score, the assisted-recovery delta, career level, YOE band, strengths and gaps.</sub>

<img src="assets/example/questiongrade.png" alt="Per-question breakdown" width="700">

<sub>**Per-question breakdown.** The scenario, the redacted response, and the refinement probe.</sub>

<img src="assets/example/practicalprac.png" alt="Assessment, scores, literature" width="700">

<sub>**Assessment and scores.** Per-question assessment, the B1-B5 pre/post score table, two literature picks, and a separate practical-exercises embed.</sub>

<img src="assets/example/bands.png" alt="/bands output" width="700">

<sub>**`/bands`.** The B1-B5 ladder with framework citations and industry-ladder mapping, plus a calibration verdict against your latest run.</sub>

<img src="assets/example/analyze.png" alt="/analyze bias output" width="700">

<sub>**`/analyze bias`.** Fields you have over-indexed relative to even coverage, with a diverging bar chart.</sub>

## Methodological Discipline

FortifAI is at v1.1: the phase pipeline and the LLM contract are stable and in daily use. Off-the-shelf LLMs will happily quiz you, but difficulty drifts, topics skew fashionable, and the rubric is whatever the model invents that turn. Four constraints hold every call to a fixed standard.

1. **Cited band ladder.** Every system prompt is stitched from cited sources: the cross-domain Dreyfus skill stages ([`templates/dreyfus.md`](templates/dreyfus.md)), the domain's seniority frameworks ([`templates/swe/score.md`](templates/swe/score.md), SWECOM and SFIA for SWE), then the procedural template (`generation.md`, `grader_question.md`, or `refine.md`). Generator and grader see the same ladder, and every band score's `reason` quotes verbatim text from a published source during assesment.
2. **Strict output contracts.** Every LLM call is parsed against a JSON schema and validated; a failure retries once with the validator's error echoed back. 5 Questions every run, with failure to submit a response at any one and any stage resulting in the run being terminated. Literature must be exactly 2 entries per question, and the growth/remediation mix is fixed by the post-refinement score.
3. **Deterministic aggregation.** Every scoring calculation (the run aggregate, the band ceiling, cross-run deltas) runs in code, not in the model. Reference-guided per-question judging and keeping threshold logic outside the judge are the largest reliability levers in LLM-as-judge work (Zheng et al., 2023). The numeric thresholds themselves, like what score counts as a ceiling or where a career-level keyword cuts, are design heuristics anchored to the score table's own definitions, not external measurements. They sit in [`templates/band_mappings.yaml`](templates/band_mappings.yaml) and [`phases/grading.py`](phases/grading.py) so they tune in one place.
4. **Field-rotation weighting.** When fields are not given explicitly, the generator weights toward fields with fewer recorded topics in `meta.json`, countering the LLM's pull toward systems, ML, and AI content and the user's tendency to revisit familiar topics.

## Accelerate Understanding

Ad-hoc AI study scatters across disconnected chat sessions. The protocol turns separate runs into one tracked loop, optimizing discipline and literature sourcing.

- **Difficulty stays at your band.** A fully-mastered practitioner at the target band can score 5 of 5; a practitioner one band below caps at 3 of 5. Drift is constrained in both the generator prompt and the validator ([phases/generation.py](phases/generation.py)).
- **Literature is scoped to your level.** The grader's reading mix is deterministic, set by your post-refinement score at your primary band: 5 gives two growth picks, 4 gives one growth and one remediation, 3 or below gives two remediation. Enforced in [phases/grading.py](phases/grading.py).
- **Growth is tracked.** `meta.json` catalogs field and topic coverage across runs. `/analyze trends|gaps|bias` shows where you have improved, where you have not been tested, and where you are over-indexing. `/sessionend` emits a deduplicated reading list for the whole session.

## Phases

A single quiz run executes four phases. Phases 0, 2, and 4 are LLM-driven; phases 1 and 3 collect user answers in the Discord layer.

| Phase | Module | What it does |
| --- | --- | --- |
| **0: Generation** | [phases/generation.py](phases/generation.py) | One LLM call. Produces 5 scenario questions, one per field, calibrated to a target band. System prompt: `dreyfus.md` + `score.md` + `generation.md`. |
| **1: Answer** | [main.py](main.py) (interactive) | Discord thread collects each answer on a 10-minute countdown. Recall on the fly, not a research window. |
| **2: Refinement** | [phases/refinement.py](phases/refinement.py) | One LLM call per question. Probes the highest-leverage ambiguity with a quoted-substring follow-up. Falls back deterministically if validation keeps failing. |
| **3: Refined answer** | [main.py](main.py) (interactive) | Discord collects the follow-up reply on a 5-minute countdown. |
| **4: Grading** | [phases/grading.py](phases/grading.py) | Five sandboxed LLM calls, one per question, each scoring against all 5 bands in isolation. Deterministic code then assembles the aggregate, deltas, and per-question breakdown. When prior runs exist to compare against, one small extra call synthesizes cross-question themes. System prompt: `dreyfus.md` + `score.md` + `invariants.md` + `grader_question.md`. |

Each phase has its own validator (`_validate_generation`, `_validate_refinement`, `_validate_question_result`) enforcing the JSON schema before a result is accepted.

## Architecture

Three packages plus a few supporting modules. Public import paths stay stable through thin facades.

```
content/         Presentation: design tokens, embed builders, charts
  shared.py        colors, icons, build(), embed helpers
  charts.py        matplotlib chart builders
  quiz.py          question / refinement / run-complete embeds
  session.py       session rollup embed
  stats.py         analytics-to-embed renderer
  analyze.py       analytics-to-embed renderer

phases/          LLM phase logic and deterministic grading
  shared.py        template loader, JSON extraction, list_industries
  generation.py    Phase 0: generate(), build_generation_system()
  refinement.py    Phase 2: refine(), _deterministic_fallback()
  grading.py       Phase 4: per-question grading + deterministic stitch
  band_data.py     band_mappings.yaml loader + table renderers
  movement.py      cross-run deltas, coherence gradient, comparison points

commands/        Discord command handlers, one module per family
  shared.py, confirm.py
  knowledgeharden.py, transcript.py, sweep.py
  session.py, schedule.py
  stats.py, analyze.py
  bands.py, rubric.py, directory.py, help.py

# Root modules:
main.py          Discord client lifecycle and command registration
parse.py         sessions, runs, meta.json (filesystem-backed state)
analytics.py     StatsView / AnalyzeView pure-data aggregators
llm.py           Anthropic SDK wrapper, prompt caching, streaming
scheduler.py     APScheduler-backed reminders (sqlite)
generate.py      facade over phases/
embeds.py        facade over content/ embeds
charts.py        facade over content/ charts
templates/       dreyfus.md, band_mappings.yaml, per-industry prompts
```

### Dependency direction

`content/` builds up from `content.shared` (design tokens) to the per-surface embed builders, exposed through the `embeds` and `charts` facades. `phases/` builds up from `phases.shared` (template loader, JSON extraction) to the phase modules, exposed through the `generate` facade. `analytics.py` reads `parse.py` and produces pure data; `content/stats.py` and `content/analyze.py` render it. Command handlers stay thin: fetch a view, hand it to a renderer, send.

## Public Surface

To port FortifAI to another front end you need three things: the phase functions, the state layer, and the analytics aggregators. Everything below re-exports through a stable facade.

**Phases** ([generate.py](generate.py)) are the LLM contract.

```python
generate.generate(*, industry, fields, topics, answerer_band, domain, stack, context_notes) -> dict
generate.refine(*, question_id, question_record, answerer_band, industry) -> dict
generate.grade(*, industry, answerer_band, current_run, entry_state=None, comparison_points=None) -> dict

generate.list_industries() -> list[str]
generate.build_generation_system(industry) -> str
generate.build_question_grader_system(industry) -> str
generate.build_stitch_grader_system(industry) -> str

# Errors: generate.GenerationError, generate.RefinementError, generate.GradingError
```

**State** ([parse.py](parse.py)) is filesystem-backed sessions, runs, and the meta.json knowledge graph. The core entry points are `create_session`, `persist_run`, `apply_grading`, and `read_meta`; `runs_needing_grading` and `cleanup_abandoned_runs` back `/sweep`. `CANONICAL_FIELDS` and `VALID_BANDS` define the taxonomy.

**Analytics** ([analytics.py](analytics.py)) produces pure `StatsView` / `AnalyzeView` records (`runcount_stats`, `timeline_stats`, `analyze_trends`, `analyze_gaps`, `analyze_bias`). Rendering is separate by design.

**Rendering** ([embeds.py](embeds.py), [charts.py](charts.py)) is Discord-flavored: embed builders, send-time chunking that keeps payloads under Discord's per-message caps, and matplotlib chart builders. Reuse only if your surface speaks embeds.

## Quickstart

Requires Python 3.14, `pipenv` (or pip and a venv), an Anthropic API key, and a Discord bot application.

```sh
# 1. Install dependencies.
pipenv install         # or: pip install -r requirements.txt

# 2. Configure secrets.
cp .env.example .env
# Set DISCORD_BOT_TOKEN and ANTHROPIC_API_KEY. Optionally set DEV_GUILD_ID
# for instant slash-command sync during development.

# 3. Run the bot.
pipenv run python main.py
```

On first run the app creates `data/` (active sessions, scheduler db, meta.json) and `sessions/` (archived closed sessions). Both are gitignored.

## Configuration

| Knob | Where | Effect |
| --- | --- | --- |
| **Models** | `MODEL_GENERATE`, `MODEL_REFINE` env vars | Defaults: `claude-opus-4-7` for generate and grade, `claude-sonnet-4-6` for refine. The grader uses `MODEL_GENERATE`. |
| **Add a domain** | `templates/<slug>/` | Discovery needs `generation.md` and `refine.md`. Full generation and grading also need `score.md`, `grader_question.md`, `grader_stitch.md`, and optionally `invariants.md`. The slug becomes selectable in `/knowledgeharden`. |
| **Cross-domain skill stages** | [`templates/dreyfus.md`](templates/dreyfus.md) | Verbatim Dreyfus stage definitions, stitched on top of every domain. |
| **Band ladder** | [`templates/band_mappings.yaml`](templates/band_mappings.yaml) | Single source of truth for B1-B5 metadata, score thresholds, and the critical-failure config. Rendered into `score.md` and `grader_question.md` at build time. |
| **Domain frameworks** | `templates/<industry>/score.md` | Verbatim citations for the domain's seniority frameworks (SWECOM and SFIA for SWE). |
| **Mechanism floors** | `templates/<industry>/invariants.md` | Per-field, per-band mechanism checks. An answer that reads fluently but misses the band's mechanism is capped at score 3. Optional; shipped for SWE. |
| **Band-tuning hints** | [`phases/generation.py`](phases/generation.py) `_BAND_GUIDANCE` | Per-band one-liner framing the difficulty tier the generator should target. |
| **Field-rotation weighting** | [`phases/generation.py`](phases/generation.py) `_select_fields_for_run` | Weights under-covered fields higher; explicit user picks bypass the weighting. |
| **Literature mix rule** | [`phases/grading.py`](phases/grading.py) `_validate_question_result` | Score 5 gives 2 growth, 4 gives 1 growth and 1 remediation, 1-3 gives 2 remediation. Enforced at validation. |
| **Canonical fields** | [`parse.py`](parse.py) `CANONICAL_FIELDS` | The 8 engineering fields and their SFIA skill mappings. |
| **Instant command sync** | `DEV_GUILD_ID` env var | Without it, slash-command changes propagate through Discord's global tree over roughly an hour. |

## Discord Caveats

- **Tied to discord.py.** All handlers in [commands/](commands/) assume a `discord.Interaction`.
- **One bot identity per deployment**, via `DISCORD_BOT_TOKEN`. Forks should register their own at [the Discord developer portal](https://discord.com/developers/applications).
- **Permissions:** read and send messages, create public threads (used by `/knowledgeharden`), manage messages in those threads. Scheduled reminders DM the user, so the user must allow DMs from server members.
- **Porting off Discord:** keep [phases/](phases/), [parse.py](parse.py), [analytics.py](analytics.py), [llm.py](llm.py); replace [commands/](commands/) and [main.py](main.py) with your front end. Reuse [content/](content/) only if your surface speaks Discord-style embeds.

## Token Cost

A per-user, per-session token tracker is not built yet. The numbers below are unmeasured order-of-magnitude estimates from prompt sizes. Do not budget against them.

| Call | Model | Token budget |
| --- | --- | --- |
| 1 generation | `MODEL_GENERATE` (Opus) | One call, `max_tokens` 4000. |
| Up to 5 refine | `MODEL_REFINE` (Sonnet) | One call per question, `max_tokens` 4000. |
| 5 grading, plus up to 1 stitch | `MODEL_GENERATE` (Opus) | One sandboxed call per question at `max_tokens` 12000, with one bump to 20000 on truncation, plus one small cross-question call when prior runs exist to compare. |

Two things are measured and in code, not estimated:

- **Prompt caching** ([llm.py](llm.py)). System prompts are sent with `cache_control: ephemeral`, so repeat calls read the stitched prompt from Anthropic's cache at the documented cache-read rate, a fraction of the base input price.
- **Streaming** ([llm.py](llm.py)). Every call streams, required for the grading budget and applied uniformly so the call site stays simple.

Grading dominates cost: it is the most calls, the largest prompts, and runs on Opus. Until the tracker lands, treat each run as non-trivial Opus spend and watch your Anthropic console.

## Repo Layout

```
.
├── README.md
├── .env.example          # documented env vars; copy to .env
├── main.py               # Discord lifecycle and command registration
├── parse.py              # sessions, runs, meta.json (filesystem state)
├── analytics.py          # StatsView / AnalyzeView pure data
├── llm.py                # Anthropic SDK wrapper, caching, streaming
├── scheduler.py          # APScheduler reminders (sqlite)
├── generate.py           # facade over phases/
├── embeds.py             # facade over content/ embeds
├── charts.py             # facade over content/ charts
├── commands/             # Discord command handlers
├── content/              # presentation: embeds, charts, design tokens
├── phases/               # LLM phase logic and deterministic grading
├── templates/            # dreyfus.md, band_mappings.yaml, per-industry prompts
├── assets/               # logo and icons (icons from Lucide, https://lucide.dev)
├── docs/                 # gitignored: local design notes
├── data/                 # gitignored: runtime state
└── sessions/             # gitignored: archived sessions
```

## Changelog

Single-author project, released as a reference implementation. The Discord front end is in regular use and the phase pipeline is stable.

### Recent

- **Grader split into per-question calls.** The monolithic grader is now five sandboxed calls, one per question, each scoring against all five bands with no carryover. Run-level aggregation and deltas moved into deterministic code ([phases/grading.py](phases/grading.py), [phases/movement.py](phases/movement.py)); the run-complete and `/transcript` embeds ([content/quiz.py](content/quiz.py)) are the single canonical display path. Per Zheng et al. (2023), keeping threshold and aggregation logic out of the judge reduces variance.
- **Band ladder consolidated.** Band-to-framework mapping is one file, [`templates/band_mappings.yaml`](templates/band_mappings.yaml), rendered into `score.md` and `grader_question.md` at build time. Removes a prior off-by-one between surfaces.
- **Mechanism floors.** [`templates/swe/invariants.md`](templates/swe/invariants.md) defines per-field, per-band mechanism checks. A fluent answer that misses the band's mechanism is capped at score 3 by rule.
- **Unassisted headline.** The run headline shows the pre-refinement (unassisted) aggregate; the post-refinement gain sits beside it as assisted recovery, so refinement scaffolding cannot inflate the top-line number.
- **Distribution guard.** When the unassisted run has two or more questions failing at the primary band, the headline replaces the career-level keyword with the failure count, so a polarized run cannot hide gaps.
- **Full SFIA facets.** The SFIA mapping carries all five generic-attribute facets (autonomy, complexity, influence, knowledge, business skills); the grader's per-band reason must consider all five.

### Planned

A May 2026 self-audit listed eleven ways the tool could mislead a studier. Six remain open, each paired with the experiment that would falsify "this is fine," documented in `docs/falsifiability-roadmap.md` (local-only):

- **Reliability harness (A).** No inter-run agreement check or model-upgrade regression gate yet. Needs a frozen answer corpus with two-rater human scores.
- **Rubric gameability (C).** Mechanism floors catch empty answers; gratuitous framework vocabulary in a mechanism-satisfied answer is a smaller residual risk.
- **Citation drift (F).** [`templates/dreyfus.md`](templates/dreyfus.md) labels synthesized stage summaries as "verbatim." They need either primary-source quotes with page numbers or a relabel.
- **Threshold cliffs (H).** Keyword cuts are hard boundaries; a small score change near a cut can flip the keyword without a real competence change. Needs a near-threshold annotation.
- **Target ambiguity (J).** The report blends three frameworks; a studier preparing for one specific adjudicator gets an averaged recommendation, not a target-specific one.
- **Coverage drift (K).** The taxonomy is 8 fields; SWEBOK v4 has 18 knowledge areas. Long study arcs can leave whole areas untested.

Also open: the token tracker, more industry templates, and a non-Discord front end.

## License

MIT. The codebase is free to use, fork, and improve.

The **FortifAI** name and logo are not part of the MIT grant. Forks may reuse the code freely; redistribution under the FortifAI name or branding requires explicit consent.

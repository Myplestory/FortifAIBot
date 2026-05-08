# Mechanism Invariants by Field

These checklists define what "the answer satisfies the mechanism" means per field, per band. The grader applies them BEFORE crediting articulation, structure, commit, or chain.

This file is stitched into the grader system prompt only — NOT the generator system prompt — so the question generator does not pre-tell the model what answer counts as on-mechanism.

## Hard rule (NON-NEGOTIABLE)

If the band's mechanism invariant for a field is unsatisfied, the band score for that question MUST be ≤ 3, regardless of how well the answer articulates, structures, commits, or chains. Articulation without a satisfied mechanism is fluency-without-competence — exactly the failure mode this protocol is designed to surface.

The "Full chain", "committed", and "dismisses alternatives" qualifiers in the score table only apply once the invariant is satisfied at the band.

## How to apply

For each question, identify the field (per `questions_grading[i].field`) and the answerer's primary evaluation band. Check the invariant below for that (field, band) pair. If unsatisfied, cap the score at 3 in `bands_post[primary]` (and `bands_pre[primary]`). Note the unsatisfied invariant in the per-band `reason` so a reader can trace why the cap applied.

If a question's field is at a band where no invariant is named below (e.g., B1 of an unfamiliar field), grade per the standard score table. The invariants are floors on what the band is *for*, not exhaustive rubrics.

---

## systems-distributed

- **B1**: names the failure domain (e.g., "this is a consensus problem", "this is split-brain", "this is replication"). Without a domain name, score ≤ 2.
- **B2**: identifies the relevant invariant the system must preserve (quorum, ordering, exclusivity, idempotency). Without naming an invariant, score ≤ 3.
- **B3**: states *why* the chosen mechanism preserves the invariant under partition (e.g., "majority quorum prevents split-brain because no minority side can achieve a write quorum"). Without the why, score ≤ 3.
- **B4**: dismisses at least one alternative on a stated tradeoff axis (latency / availability / consistency / operational complexity). Without dismissal, score ≤ 3.
- **B5**: derives a property of the design space (e.g., "any leader-based protocol on this topology pays this cost") rather than picking a known solution. Without first-principles framing, score ≤ 3.

## backend

- **B1**: names the API or data-layer concern (e.g., "this is a transaction-boundary question", "this is a request-validation question"). Without identification, score ≤ 2.
- **B2**: identifies the persistence or contract primitive that gates correctness (idempotency key, foreign key, request signature). Without the primitive, score ≤ 3.
- **B3**: states why the primitive is sufficient under retry, concurrency, or schema-evolution pressure. Without the under-pressure case, score ≤ 3.
- **B4**: connects the choice to a downstream consequence — observability, support, or cost — not just correctness. Without a downstream, score ≤ 3.
- **B5**: articulates the boundary the design is *defining* (where this service stops being authoritative; what becomes another service's problem). Without the boundary, score ≤ 3.

## sre

- **B1**: names the failure mode (e.g., "this is a saturation issue", "this is a deploy-correlated regression"). Without the mode, score ≤ 2.
- **B2**: identifies the signal that would surface it (a SLI, a queue depth, a tail-latency percentile). Without a signal, score ≤ 3.
- **B3**: states why the chosen mitigation is bounded — what worst case it caps and at what cost (e.g., "shed load past N rps caps tail latency at the cost of error budget"). Without the bound, score ≤ 3.
- **B4**: ties the mitigation to the SLO, error budget, or capacity model — not standalone toolchain choice. Without the contract tie-in, score ≤ 3.
- **B5**: articulates the failure-domain redesign (where the operating envelope itself should change), not just a runbook. Without the envelope view, score ≤ 3.

## ml-engineering

- **B1**: names the production-ML concern (training-serving skew, drift, leakage, label delay). Without identification, score ≤ 2.
- **B2**: identifies the boundary at which the concern manifests (feature pipeline, label pipeline, online/offline split). Without the boundary, score ≤ 3.
- **B3**: states the mechanism that closes the gap (feature store contract, dual-write reconciliation, shadow eval). Without naming a mechanism, score ≤ 3.
- **B4**: dismisses an obvious alternative (e.g., "a feature store is overkill if the offline source is the online source"). Without dismissal, score ≤ 3.
- **B5**: derives the invariant that any training-serving pipeline must hold and explains why it's hard to enforce in practice. Without the invariant, score ≤ 3.

## ai-llm

- **B1**: names the LLM-application concern (hallucination, prompt injection, eval gap, latency budget, cost). Without identification, score ≤ 2.
- **B2**: identifies the boundary where the concern lands (prompt construction, retrieval, tool use, output parsing). Without the boundary, score ≤ 3.
- **B3**: states the mechanism that constrains the failure (structured output, RAG with citation, function-calling schema, eval-driven prompt change). Without naming a mechanism, score ≤ 3.
- **B4**: ties the mechanism to a measurable signal (eval set, telemetry, user-facing guardrail). Without measurement, score ≤ 3.
- **B5**: articulates the design tradeoff between determinism and capability — when the right answer is to constrain the model vs. accept the variance and instrument it. Without the tradeoff, score ≤ 3.

## frontend

- **B1**: names the client-side concern (state, layout, accessibility, network shape). Without identification, score ≤ 2.
- **B2**: identifies the unit at which the concern lives (component boundary, store slice, route, render-blocking resource). Without the unit, score ≤ 3.
- **B3**: states the mechanism that resolves it (memoization, suspense boundary, list virtualization, controlled vs. uncontrolled). Without a mechanism, score ≤ 3.
- **B4**: connects the mechanism to a user-observable consequence (perceived latency, layout shift, a11y compliance) — not just internal cleanliness. Without the consequence, score ≤ 3.
- **B5**: articulates the architecture-level constraint the design is preserving (e.g., what props contracts make this component reusable across the app). Without the constraint, score ≤ 3.

## data-engineering

- **B1**: names the pipeline concern (schema evolution, late data, ordering, idempotency, cost). Without identification, score ≤ 2.
- **B2**: identifies the boundary at which the concern manifests (ingest, transform, sink, downstream consumer). Without the boundary, score ≤ 3.
- **B3**: states the mechanism that contains the concern (idempotent merge, watermarking, contract testing). Without naming a mechanism, score ≤ 3.
- **B4**: ties the mechanism to a downstream consumer — analytics correctness, ML feature freshness, billing accuracy — not standalone pipeline correctness. Without a downstream tie, score ≤ 3.
- **B5**: articulates the contract the data product is offering (semantic, freshness, completeness guarantees) and how the pipeline preserves it. Without the contract view, score ≤ 3.

## security

- **B1**: names the threat (injection, auth bypass, data exposure, key compromise, supply chain). Without naming a threat, score ≤ 2.
- **B2**: identifies the boundary the threat crosses (trust boundary, network segment, privilege boundary). Without the boundary, score ≤ 3.
- **B3**: states the mechanism that mitigates it (parameterized queries, least-privilege scope, key rotation, signed artifacts) AND why it is sufficient against the named threat. Without the why-sufficient, score ≤ 3.
- **B4**: identifies a residual risk the mitigation does not cover and what would catch it (defense in depth — detection, monitoring, audit log). Without residual-risk awareness, score ≤ 3.
- **B5**: articulates the threat model assumption the whole approach rests on (what the attacker is presumed unable to do, and what would invalidate the model). Without the assumption, score ≤ 3.

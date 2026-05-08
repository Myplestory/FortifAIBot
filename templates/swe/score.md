# Software Engineering Grading Authority — Domain-Specific Frameworks

Building on the Dreyfus model of skill acquisition (cross-domain skill-stage taxonomy, prepended above), this document specifies the two software-engineering-specific frameworks used to map skill stage onto seniority band. Reference these verbatim definitions when justifying band scores in your `reason` and `citations` fields. Any stress test of the grading methodology must be defensible against these sources together with Dreyfus.

## Source 1: IEEE SWECOM (Software Engineering Competency Model)

IEEE Computer Society, "Software Engineering Competency Model (SWECOM)," 2014. Based on SWEBOK v3.0 (ISO/IEC TR 19759:2015). Updated mapping: SFIA v9 × SWEBOK v4, October 2024.

SWECOM defines five levels of increasing competency for software engineering work activities. Each level specifies the cognitive complexity, supervision requirements, and scope of impact expected.

**Verbatim level definitions** (IEEE SWECOM, 2014, pp. 4-5):

> **Level 1 — Technician:** "An individual who is competent to follow instructions while performing an activity."

> **Level 2 — Entry Level Practitioner:** "An individual who is competent to assist in performing an activity or to perform activities with some supervision."

> **Level 3 — Experienced Practitioner:** "An individual who is competent to perform an activity with little or no supervision."

> **Level 4 — Technical Leader:** "An individual who is competent to lead and direct participants in the performance of the activities in one or more skills or skill areas."

> **Level 5 — Senior Software Engineer:** "An individual who is competent to create new, and modify existing processes, procedures, methods, and tools for performing activities, groups of activities within one or more skills, and skills within skill areas."

**Mapping to band scores:**

| SWECOM Level | Verbatim Definition | Band |
|---|---|---|
| Level 1 (Technician) | "competent to follow instructions while performing an activity" | Entry (score 1-2) |
| Level 2 (Entry Level Practitioner) | "competent to assist in performing an activity or to perform activities with some supervision" | Entry (score 3-5) |
| Level 3 (Experienced Practitioner) | "competent to perform an activity with little or no supervision" | Mid (score 3-5) |
| Level 4 (Technical Leader) | "competent to lead and direct participants in the performance of the activities in one or more skills or skill areas" | Senior (score 3-4) |
| Level 5 (Senior Software Engineer) | "competent to create new, and modify existing processes, procedures, methods, and tools" | Senior (score 5) |

**Empirical basis:** SWECOM was developed by the IEEE Computer Society's Professional & Educational Activities Board through analysis of industry practice across multiple organizations and domains. It is aligned with SWEBOK, which is an ISO/IEC standard (TR 19759) representing "generally accepted knowledge" in software engineering as validated by international expert review. SWECOM additionally notes: "An individual may be at different levels of competency for different skill areas, skills within skill areas, and activities within skills, depending on his or her educational background, work experiences, and aptitude." This supports the position that scores reflect demonstrated competency per question, not global seniority.

## Source 2: SFIA (Skills Framework for the Information Age) v9

SFIA Foundation, "SFIA 9," October 2024. Adopted by organizations in 200+ countries. Mapped to SWEBOK v4 by IEEE-CS PEAB.

SFIA defines seven levels of responsibility. The relevant levels with **verbatim definitions** from sfia-online.org:

> **Level 1 (Follow):** Autonomy: "Works under close direction. Uses little discretion in attending to enquiries. Is expected to seek guidance in unexpected situations." Complexity: "Performs routine activities in a structured environment." (SFIA 8/9, Level 1.)

> **Level 2 (Assist):** Autonomy: "Works under routine direction. Uses limited discretion in resolving issues or enquiries. Determines when to seek guidance in unexpected situations." Complexity: "Performs a range of work activities in varied environments." (SFIA 8/9, Level 2.)

> **Level 3 (Apply):** Autonomy: "Works under general direction. Receives specific direction, accepts guidance and has work reviewed at agreed milestones. Uses discretion in identifying and responding to complex issues related to own assignments. Determines when issues should be escalated to a higher level." Complexity: "Performs a range of work, sometimes complex and non-routine, in a variety of environments." Essence: "Performs varied tasks, sometimes complex and non-routine, using standard methods and procedures. Works under general direction, exercises discretion, and manages own work within deadlines." (SFIA 9, Level 3.)

> **Level 4 (Enable):** Autonomy: "Works under general direction within a clear framework of accountability. Exercises substantial personal responsibility and autonomy. Uses substantial discretion in identifying and responding to complex issues and assignments as they relate to the deliverable/scope of work." Complexity: "Work includes a broad range of complex technical or professional activities, in a variety of contexts." Influence: "Influences customers, suppliers and partners at account level. Makes decisions which influence the success of projects and team objectives." (SFIA 8/9, Level 4.)

> **Level 5 (Ensure, advise):** Autonomy: "Works under broad direction. Work is often self-initiated. Is fully accountable for meeting allocated technical and/or group objectives." Complexity: "Performs an extensive range and variety of complex technical and/or professional work activities. Undertakes work which requires the application of fundamental principles in a wide and often unpredictable range of contexts." Influence: "Influences organisation, customers, suppliers and partners. Makes decisions which impact the success of assigned work, i.e. results, deadlines and budget. Has significant influence over the allocation and management of resources appropriate to given assignments." (SFIA 8/9, Level 5.)

**Mapping to band scores (all five SFIA generic-attribute facets):**

SFIA's responsibility ladder is defined by five generic attributes — autonomy, complexity, influence, knowledge, business skills. Earlier versions of this mapping captured only autonomy and complexity, which let answers satisfy the rubric while ignoring influence/knowledge/business — exactly the failure mode the grader has to avoid. The full table:

{{SFIA_FACETS_TABLE}}

When the grader assigns a band score, the per-band `reason` MUST reflect consideration of all five facets at the answerer's primary band. See `templates/swe/grader.md` → "SFIA Reason Coverage Invariant" for the rule.

**Empirical basis:** SFIA has been maintained since 2000 and is used by organizations globally for workforce planning, skills assessment, and career development. Its levels are calibrated against market salary benchmarks and organizational role definitions across industries. The SFIA Foundation is a global not-for-profit organization; the framework is freely accessible and updated through industry consultation.

## Mapping Invariants — YOE Bands

The YOE ranges (Entry: 0-2, Mid: 2-5, Senior: 5+) are approximate anchors, not deterministic. They are derived from:

- SWECOM's observation that progression through competency levels requires "relevant experience" but that "an individual may be at different levels of competency for different skill areas."
- The Dreyfus model's finding that the novice → competent transition requires "considerable experience" (empirically observed at 2-4 years in studied domains).
- Industry engineering ladder data: Google's L3-L4 (0-2 YOE), L4-L5 (2-5 YOE), L5+ (5+ YOE) mapping is the most widely referenced industry ladder and aligns with these bands.

**The YOE bands set a baseline expectation. An individual may score above or below their YOE band. The score reflects demonstrated competency on the specific question, not years served.**

## How to use this authority

When you assign band scores in `bands_pre` or `bands_post`, your `reason` field should anchor to the verbatim phrases above. When you propose new citation keys in `meta_updates.criteria_set[<field>][<band>].citations`, prefer keys that point to the source paragraphs in this document (e.g., `dreyfus.competent.analytical-rule-following`, `swecom.l3.little-or-no-supervision`, `sfia.l4.substantial-autonomy`).

The procedural grading rules — output schema, score-per-band table, literature surfacing, delta computation, redaction — follow below.

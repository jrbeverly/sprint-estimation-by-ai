# VISION.md

# AI-Assisted Continuous Estimation

## Vision

Estimation should be a lightweight, continuously improving input to product delivery—not a recurring exercise that consumes large amounts of team attention.

The goal of this system is to make estimation largely automatic by combining:

- the team's historical estimates,
- actual execution effort and outcomes,
- the nature and characteristics of the work,
- recurring sources of complexity and uncertainty,
- and continuous feedback from completed work.

AI is used as a heuristic reasoning layer over this evidence.

It does not need to produce a mathematically perfect estimate for every individual work item. It needs to produce estimates that are directionally useful, consistently calibrated, and increasingly reliable across the body of work.

Humans remain responsible for correcting estimates that are obviously wrong, supplying missing context, and identifying exceptional work. They should not need to repeatedly perform detailed estimation ceremonies simply to produce planning numbers.

---

## Core Idea

Every work item entering the Product Development Lifecycle receives an AI-generated estimate.

The AI evaluates the work against a continuously maintained estimation model containing learned factors such as:

- ambiguity,
- technical novelty,
- unfamiliar code or systems,
- dependency count,
- cross-team coordination,
- migration complexity,
- operational risk,
- testing burden,
- infrastructure impact,
- legacy-system interaction,
- security or compliance requirements,
- reversibility,
- external dependencies,
- and other recurring properties observed in historical delivery.

These factors are not intended to become rigid categories.

A work item does not need to be assigned to a single "type." Instead, the system treats characteristics as overlapping signals that influence the expected effort.

Conceptually:

```text
Base understanding of work
        +
Observed work characteristics
        +
Team execution history
        +
Known estimation bias
        +
Current uncertainty
        ↓
Heuristic AI estimate
```

The resulting estimate is then compared with actual execution data once the work is complete.

Those observations become evidence for future estimation.

---

# Product Development Lifecycle

## 1. Intent

Work begins as an outcome, problem, requirement, or proposed change.

At this stage the objective is not to estimate it.

The objective is to establish enough understanding that the system can reason about what is being proposed.

Typical inputs may include:

- product requirements,
- technical direction,
- acceptance criteria,
- architecture context,
- constraints,
- dependencies,
- risks,
- related work,
- and known unknowns.

The output is a work item sufficiently described for planning.

```text
Idea / Outcome
      ↓
Product & Technical Context
      ↓
Estimatable Work Item
```

---

## 2. Initial AI Estimation

The estimation agent analyzes the work item.

It considers:

1. the apparent size of the work,
2. the characteristics present in the work,
3. comparable historical work,
4. the team expected to perform it,
5. known historical estimation bias,
6. uncertainty in the available information.

It then generates:

- an estimate,
- an uncertainty or confidence indication,
- the important factors influencing the estimate,
- and optionally the historical analogues that informed it.

Example:

```yaml
estimate: 5
confidence: medium

factors:
  - unfamiliar subsystem
  - external service dependency
  - moderate test surface
  - low deployment complexity

notes:
  - similar integration work has historically exceeded base estimates
  - implementation itself appears small
  - external dependency introduces schedule uncertainty
```

The explanation exists primarily for inspection and debugging.

It should not become another required human ceremony.

---

## 3. Human Sanity Check

Humans review the estimate only to identify clear failures.

Examples:

- the AI misunderstood the requested work,
- a critical dependency is missing,
- the work contains a known hidden constraint,
- the estimate is obviously inconsistent with similar work,
- the scope represented by the ticket is incorrect.

The expected interaction should normally be:

```text
AI Estimate
    ↓
Looks Reasonable?
 ┌───────┴────────┐
Yes              No
 │                │
Continue      Correct context
                  │
                  └──→ Re-estimate
```

The system should not require humans to independently create an estimate before seeing the AI estimate.

Doing so would preserve the estimation workload the system is intended to remove.

---

## 4. Sprint / Iteration Planning

AI-generated estimates become planning inputs.

They may be used for:

- sprint capacity,
- iteration planning,
- sequencing,
- scenario analysis,
- backlog shaping,
- workload balancing,
- delivery forecasting,
- identifying unusually uncertain work.

The system should favour aggregate usefulness over artificial precision.

An individual estimate may be wrong.

The important question is whether the collection of estimates gives the team a useful representation of expected work.

---

## 5. Execution

The team performs the work normally.

The estimation system should avoid becoming an execution-management burden.

During execution, useful evidence may be collected automatically where available:

- active engineering time,
- elapsed cycle time,
- review effort,
- number of implementation iterations,
- unexpected dependency work,
- scope changes,
- incidents or rollbacks,
- testing expansion,
- rework,
- blocked periods.

The system should distinguish, where practical, between:

```text
Engineering Effort
```

and:

```text
Elapsed Delivery Time
```

A ticket that required one day of engineering but remained blocked for five days should not automatically teach the system that the engineering work requires six days.

Both signals may be useful, but they describe different things.

---

## 6. Completion and Outcome Capture

Once the work is complete, the system records the outcome.

At minimum:

```text
AI Estimate
Actual Observed Effort
Difference
Relevant Work Factors
Team
```

Where appropriate, the system may also capture:

- unexpected work,
- changed scope,
- newly discovered dependencies,
- estimation overrides,
- execution anomalies,
- and delivery delays unrelated to engineering effort.

The purpose is not to create a detailed retrospective for every work item.

The purpose is to create structured evidence.

---

## 7. Continuous Calibration

Completed work becomes calibration data.

The system periodically analyzes whether particular factors, combinations of factors, teams, or work patterns cause systematic estimation error.

For example:

```text
Work touching unfamiliar infrastructure
    historically takes more effort than predicted

Cross-team dependency + migration work
    regularly produces substantial overruns

Routine application changes
    are consistently being overestimated

Security review requirements
    increase elapsed delivery time but only modestly increase engineering effort
```

The system can then update its working estimation guidance.

This guidance may be represented as a continuously generated page or knowledge artifact used by the estimation agent.

Example conceptual model:

```text
Historical Work
      ↓
Outcome Analysis
      ↓
Learned Factors / Relationships
      ↓
Generated Estimation Guidance
      ↓
Future AI Estimates
      ↓
New Historical Work
      └───────────────────────↺
```

---

# Factor Model

The estimation model should not depend on a rigid taxonomy of work.

Instead it should reason using overlapping factors.

A piece of work may simultaneously be:

```text
Small implementation
+ unfamiliar subsystem
+ high testing burden
+ external dependency
+ low operational risk
```

Each factor changes the expected effort.

The relationship between factors may also matter.

For example:

```text
Factor A → roughly 2× difficulty
Factor B → roughly 5× difficulty
```

The system does not need to mechanically calculate:

```text
2 × 5 = exactly 10
```

The desired behaviour is simply that work containing both factors receives substantially more weight than work containing either factor independently.

AI is therefore being used for approximate composition of evidence rather than exact arithmetic.

The objective is a useful heuristic model.

---

# Estimation Knowledge Artifact

The system should maintain an authoritative estimation reference generated from historical evidence.

This reference represents the current understanding of how the team delivers work.

It may contain observations such as:

```text
The team is generally accurate on routine application changes.

Infrastructure migrations tend to exceed initial estimates substantially.

Work involving unfamiliar third-party APIs has high variance.

Cross-team coordination primarily affects elapsed time rather than engineering effort.

Large testing surfaces are currently underweighted in estimates.
```

The reference should be regenerated or compacted as new evidence accumulates.

Older versions may be retained for auditability, but estimation agents should consume the current authoritative version.

This allows the system to learn without requiring a permanently growing prompt containing every historical ticket.

---

# Feedback Model

There are two distinct feedback loops.

## Work-Level Feedback

For each completed item:

```text
Expected
   ↓
Executed
   ↓
Observed Error
   ↓
Evidence
```

This provides raw calibration data.

## System-Level Feedback

Across many completed items:

```text
Historical Evidence
      ↓
Systematic Bias Detection
      ↓
Updated Estimation Guidance
      ↓
Future Estimates
```

This is the more important loop.

The goal is not to eliminate variance in individual work items.

The goal is to eliminate systematic estimation bias.

---

# Human Role

Humans remain responsible for judgment.

The AI should remove repetitive estimation work, not remove human oversight.

Humans should primarily intervene when:

- context is missing,
- the scope is misunderstood,
- an estimate is clearly unreasonable,
- a genuinely novel condition exists,
- or the system is demonstrating persistent bias.

A healthy operating model is:

```text
AI estimates everything
Humans inspect exceptions
System learns from outcomes
```

rather than:

```text
Humans estimate everything
AI records the estimates
```

---

# Success Criteria

The system should not be judged primarily on exact per-ticket prediction accuracy.

A useful system may still be wrong on many individual work items.

Success should instead be measured through aggregate behaviour.

Key measures include:

## Calibration

Across a sufficiently large body of work:

```text
Estimated effort ≈ Actual effort
```

Systematic underestimation or overestimation should decrease over time.

## Bias by Factor

The system should identify whether particular characteristics repeatedly produce estimation error.

For example:

```text
Migration work: +38% historical underestimate
Routine UI work: -12% historical overestimate
External dependencies: high variance
```

## Human Override Rate

How often does a human need to reject or materially alter an AI estimate?

The desired direction is downward.

## Planning Reliability

Does estimated sprint or iteration capacity meaningfully correspond to actual delivered effort?

## Estimation Ceremony Reduction

How much human effort is spent generating estimates?

The desired outcome is substantially less.

## Retrospective Burden

How frequently does estimation failure require explicit retrospective analysis?

The ideal state is a significant lack of estimation-related back-analysis.

If the system is operating well, normal delivery outcomes should continuously calibrate it without humans repeatedly asking:

> Why was this estimate wrong?

The feedback loop should answer that question automatically at the system level.

---

# Failure Modes to Avoid

## False Precision

The system should not imply that estimates are deterministic.

Values such as:

```text
4.73 engineering days
```

create precision without corresponding certainty.

Approximate estimates and confidence bands are preferable.

---

## Taxonomy Explosion

The system should not create hundreds of rigid work categories.

Real work is multi-dimensional.

Factors and relationships are more useful than mutually exclusive classifications.

---

## Human Estimation by Proxy

The system has failed if humans must fill out extensive forms so the AI can estimate the work.

Context should primarily come from artifacts that already exist in the delivery process.

---

## Optimizing Individual Predictions

The system should not overreact to every incorrect estimate.

Software delivery contains unavoidable variance.

Calibration should be driven by repeated evidence rather than individual anomalies.

---

## Learning from Bad Outcome Data

Elapsed time, engineering effort, blocked time, scope expansion, and execution failure are different signals.

Treating them as interchangeable will teach the system incorrect relationships.

---

## Turning Estimates into Commitments

An estimate is evidence for planning.

It is not a guarantee.

The system should not encourage teams to manipulate estimates because they are later treated as performance commitments.

---

# Non-Goals

This system is not intended to:

- perfectly predict delivery dates,
- eliminate uncertainty,
- replace engineering judgment,
- measure individual developer productivity,
- score engineer performance,
- force all work into standardized categories,
- optimize every estimate independently,
- or create a mathematically pure estimation model.

Its purpose is simpler:

> Produce useful planning estimates automatically, learn from actual delivery, and continuously reduce systematic error.

---

# End State

The long-term experience should feel almost invisible.

A work item becomes sufficiently defined.

The AI estimates it.

A human notices only when something looks wrong.

The team executes the work.

Actual outcomes automatically become evidence.

The estimation model recalibrates.

Future work becomes slightly better estimated.

```text
Define
  ↓
Estimate
  ↓
Sanity Check
  ↓
Plan
  ↓
Execute
  ↓
Observe
  ↓
Calibrate
  └──────────────↺
```

The system succeeds when teams spend less time debating estimates while the organization gains better empirical understanding of how work actually behaves.

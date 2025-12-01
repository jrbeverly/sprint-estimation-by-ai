# Evaluation verdict — guided and unguided estimation on the held-out backlog

Computed from the recorded run directory (36 calls: 12 held-out items x
3 conditions) and the committed fixtures; replaying the run directory
without the model reproduces these numbers exactly.

Condition totals (ratio = sum of estimates / sum of actuals):

- guided: estimated 47, actual 66, total ratio 0.712
- history: estimated 49, actual 66, total ratio 0.742
- unguided: estimated 69, actual 66, total ratio 1.045

Per-factor totals (each planted factor's three held-out items):

- external-dependency: actual 24; unguided ratio 0.875, guided ratio 0.625, history ratio 0.542
- familiar-application: actual 10; unguided ratio 0.900, guided ratio 0.600, history ratio 0.900
- migration: actual 16; unguided ratio 1.500, guided ratio 0.812, history ratio 0.938

Context sizes: artifact 254 characters, raw history 51256 characters (fraction 0.0050).

## V1 baseline sanity — PASS

Numbers: unguided total ratio 1.045; bounds [0.5, 2.0]

## V2 learning transfers — FAIL

Numbers: unguided distance 0.045, guided distance 0.288; margin -0.242 (required 0.05)

## V3 compaction — PASS

Numbers: guided-vs-history ratio difference 0.030 (max 0.05); artifact 254 characters, history 51256 characters (fraction 0.0050, max 0.2)

## V4 bias recovery — FAIL

Numbers: external-dependency unguided 0.875 -> guided 0.625; familiar-application unguided 0.900 -> guided 0.600; migration unguided 1.500 -> guided 0.812

## V5 guardrails — PASS

Numbers: estimates in vocabulary 36/36; guidance matches deterministic recalibration over the committed evidence: yes; run directory files modified by the evaluation: 0

## Overall verdict

**FAIL** — 3 of 5 checks passed.

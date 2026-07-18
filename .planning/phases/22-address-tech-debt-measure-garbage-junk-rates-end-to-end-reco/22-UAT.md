---
status: testing
phase: 22-address-tech-debt-measure-garbage-junk-rates-end-to-end-reco
source: [22-VERIFICATION.md]
started: 2026-07-18T02:35:00Z
updated: 2026-07-18T02:35:00Z
---

## Current Test

number: 1
name: Decide how REQUIREMENTS.md Success Criterion #1 ("<5% garbage chunks") should be read/reworded now that a real measurement exists
expected: |
  A product/maintainer decision on whether criterion #1 is:
  (a) considered MET via export_junk_rate (0.0%, the metric representing garbage actually reaching the delivered corpus — decisively beats the <2% target), or
  (b) considered UNMET via the literal chunk_garbage_rate reading (45.64%, the gate's own live candidate-rejection rate — higher than the 28% baseline, though this is expected behavior of a working gate, not a regression), or
  (c) REQUIREMENTS.md's wording is revised to explicitly reference export_junk_rate as the intended criterion-#1 metric, as 22-03-SUMMARY.md and 22-VERIFICATION.md both recommend considering.
awaiting: user response

## Tests

### 1. Decide how REQUIREMENTS.md Success Criterion #1 should be interpreted/reworded
expected: |
  Review the Interpretive Note in 22-03-SUMMARY.md and the independent assessment in 22-VERIFICATION.md.
  Both converge on the same conclusion: the finding is genuine, correctly measured, and honestly reported —
  chunk_garbage_rate (45.64%) and export_junk_rate (0.0%) measure different things (live gate-rejection rate
  of raw candidates vs. garbage in already-delivered content). The "is criterion #1 met" question is a
  definitional/product judgment about the milestone's original intent, not something code inspection can
  resolve. This decision affects whether v2.6's tech-debt item #2 (from .planning/v2.6-MILESTONE-AUDIT.md)
  is considered fully closed, or needs a small REQUIREMENTS.md wording-update follow-up.
result: [pending]

## Summary

total: 1
passed: 0
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps

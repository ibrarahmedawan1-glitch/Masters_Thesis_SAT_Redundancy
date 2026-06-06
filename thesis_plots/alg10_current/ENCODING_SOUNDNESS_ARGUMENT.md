# Algorithm 10 Encoding Soundness Argument

This note is thesis-writing material for the correctness argument behind
Algorithm 10. It states the proof obligations for the SAT encodings and the
implementation checks that support the claim.

## Scope

The circuit model is combinational AIG/AAG logic. Primary inputs and latch
current values are treated as free boundary variables. Primary outputs and
latch next-state literals are treated as observable roots. The method does not
claim sequential redundancy removal, unreachable-state reasoning, optimal AIG
optimization, or completeness when candidates remain unresolved.

The optimization action studied here is a single internal AND gate replacement
by a stuck-at constant 0 or 1. Multiple replacements are applied greedily: each
new proof is made in the currently committed circuit context.

## AIG Semantics

For an AIG literal `l`:

- `0` denotes constant false.
- `1` denotes constant true.
- an even literal `2v` denotes variable/gate value `v`;
- an odd literal `2v + 1` denotes the negation of `v`.

For each AND gate `g = a AND b`, the Boolean value of `g` under input
assignment `x` is:

```text
value(g, x) = value(a, x) AND value(b, x)
```

Because AAG gates are topologically ordered, this valuation is well-defined by
induction over the gate list.

## Tseitin Encoding Lemma

Algorithm 10 encodes each AND gate with the standard clauses:

```text
(not a or not b or out)
(a or not out)
(b or not out)
```

These clauses are satisfiable exactly when:

```text
out = a AND b
```

Proof sketch:

- If `a = b = 1`, the first clause forces `out = 1`.
- If `out = 1`, the second and third clauses force `a = 1` and `b = 1`.
- If either `a = 0` or `b = 0`, `out = 1` would violate one of the second or
  third clauses, so `out = 0`.

Thus the SAT encoding is equivalent to the AIG gate semantics.

## Global Miter Soundness

The global configurable-fault miter builds:

- a good circuit copy;
- a faulty circuit copy;
- shared variables for every primary input and latch-current boundary value;
- output/latch-next XORs between the good and faulty copies;
- an OR of these XORs as the miter literal;
- two controls per AND gate: `f0_i` for stuck-at-0 and `f1_i` for stuck-at-1;
- a mutex clause `(not f0_i or not f1_i)`.

For a faulty gate, Algorithm 10 encodes:

```text
faulty_out = (normal_out AND not f0_i) OR f1_i
```

The cases are:

- if `f0_i = 0` and `f1_i = 0`, then `faulty_out = normal_out`;
- if `f0_i = 1` and `f1_i = 0`, then `faulty_out = 0`;
- if `f0_i = 0` and `f1_i = 1`, then `faulty_out = 1`;
- `f0_i = 1` and `f1_i = 1` is forbidden by the mutex.

For a candidate check, the assumption vector enforces:

- all inactive controls disabled;
- all previously accepted replacements active;
- the candidate control active;
- the opposite candidate control disabled;
- the miter literal asserted.

The strengthened assumption audit checks not only the count `2A + 1`, but also
the literal content and polarity for every fault control and the miter
assertion.

Theorem: if the global miter is UNSAT under these assumptions, then no
primary-input/latch-current assignment can distinguish the current committed
circuit from the circuit with the additional candidate replacement. Therefore
committing that replacement preserves all observable roots.

Reason: by the Tseitin lemma and induction over the good and faulty copies, any
SAT model with the miter asserted would be exactly a concrete input assignment
where at least one observable root differs. UNSAT means no such assignment
exists.

## TFI Constancy Tier

The TFI tier encodes either the complete transitive fanin cone of the target
gate or, in the phase-local persistent implementation, the complete current
good circuit. It asks whether the target can take the opposite of the proposed
stuck value.

For proposed stuck-at-0:

```text
SAT query: target = 1
```

For proposed stuck-at-1:

```text
SAT query: target = 0
```

If the query is UNSAT, the target gate is functionally constant over all input
assignments to the cone boundary. Replacing the gate by that constant preserves
the value of the target under every assignment. Since all downstream logic sees
the same target value, every output remains unchanged.

The full-good-circuit persistent variant is also sound. Downstream gates are
encoded only by deterministic Tseitin constraints and no primary output is
forced to a value. Therefore, for any satisfying assignment of the target's
fanin cone, the downstream variables can be extended consistently by evaluating
the rest of the AIG. The full-good-circuit query is UNSAT exactly when the
opposite target value is unreachable in the target fanin cone. It is a solver
reuse optimization, not a weaker proof rule.

If the query is SAT, timeout, or skip, the tier does not reject the candidate
globally. It only means the cheap constancy proof did not succeed, so the
candidate must escalate.

## Exact Affected-Output Cone Tier

The exact cone tier finds every real observable root in the candidate gate's
fanout. It then encodes the complete fanin cones of those affected roots and
builds a good-versus-faulty miter over exactly those roots.

Observable roots outside the candidate fanout are unaffected by the candidate
replacement. Observable roots inside the candidate fanout are explicitly
compared by the cone miter.

Therefore, if this cone miter is UNSAT, the candidate replacement preserves all
observable roots and is safe to commit. SAT, timeout, or skip is inconclusive and
must escalate.

The hybrid grouped-cone implementation uses the same proof obligation but
amortizes the encoding. Candidates with identical affected observable roots may
share one configurable-fault cone miter. The grouped cone contains:

- a good copy of the complete affected-root fanin cone;
- a faulty copy of the same cone;
- stuck-at controls for gates in the cone;
- mutex clauses for each gate's `SA0` and `SA1` controls;
- assumptions that disable every inactive control, activate all previously
  committed replacements in the faulty copy, activate only the current
  candidate, and assert the cone miter literal.

This grouped query is sound for the same reason as the single-candidate cone
miter: under the assumptions, the only additional uncommitted replacement being
tested is the current candidate. Reusing the solver for later candidates in the
same unchanged phase only reuses clauses learned from the same CNF and does not
change the acceptance rule. The implementation falls back to the single-cone
encoder for small or skipped groups.

## Audited Window Tier

The bounded TFO window tier is sound only under a runtime cut condition.

The window chooses boundary roots around the candidate and encodes complete
fanin cones of those roots. A window UNSAT result is accepted only if the
runtime audit proves that the chosen roots form a complete observable cut:
every fanout path from the candidate to any real observable root must pass
through at least one window root.

If the cut audit fails, the window tier skips the candidate and escalates. If
the complete fanin cone of the window roots exceeds the configured cap, the
whole window skips. The implementation must not encode a partial root set and
accept from that partial proof.

Under the complete-cut condition, equality at all window roots implies equality
at all downstream observable roots, because every downstream influence from the
candidate passes through one of those roots. Therefore, window UNSAT is a safe
sufficient condition for committing a candidate.

Window SAT is not a proof of nonredundancy. It is inconclusive and must not be
used as an acceptance or final rejection proof.

## CEX Pruning

CEX pruning is rejection-only. It never commits a replacement.

For output-level pruning, a SAT model from a window, cone, or global miter is
converted into a concrete primary-input/latch-current assignment. The full
current circuit is then simulated for each pending candidate. A candidate is
pruned only when that candidate's own stuck-at faulty circuit differs from the
good circuit at a real observable root under the concrete assignment.

This is sound as a rejection rule for the current phase: the concrete assignment
is a witness that the candidate is observable, so the candidate is not redundant
in that committed context.

False CEX pruning is not caught by final CEC because it causes missed
reductions, not wrong outputs. Therefore Algorithm 10 includes audit mode:

- SAT in the exact observable audit miter confirms the prune;
- UNSAT means a false prune and the candidate is kept;
- timeout or skip also keeps the candidate alive.

Thus CEX pruning cannot create an incorrect output circuit. Its risk is recall,
which is measured by `CEX_Audit_False_Prunes`.

## Rewrite Soundness

After a candidate is accepted, the implementation rewrites the target gate as:

```text
lhs = constant AND constant
```

then runs structural cleanup and writes a normalized AAG. The proof obligation
is that this physical rewrite implements the same stuck-at replacement that was
proved by SAT.

The bounded exhaustive checker validates this implementation step by applying
true redundant replacements, running the production cleanup, and comparing the
rewritten circuit against brute-force truth-table semantics.

## Bounded Exhaustive Validation

The script:

```text
test_encoding_soundness_bounded.py
```

checks the production encodings against a brute-force semantic oracle. It
enumerates small AIGs and, for every stuck-at candidate, compares:

- global miter SAT result versus truth-table redundancy;
- TFI constancy result versus truth-table constancy;
- exact affected-output cone result versus truth-table redundancy;
- audited window UNSAT acceptances versus truth-table redundancy;
- rewrite/strash output after true redundant replacements versus truth-table
  equivalence.

Recent bounded exhaustive results:

```text
Run 1:
circuits = 33,588
candidates = 133,176
global checks = 133,176
TFI checks = 133,176
cone checks = 133,176
window checks = 133,176
rewrite checks = 133,176
failures = 0

Run 2:
circuits = 92,628
candidates = 536,376
global checks = 536,376
TFI checks = 536,376
cone checks = 536,376
window checks = 536,376
rewrite checks = 536,376
failures = 0
```

These tests do not prove correctness for all possible AIGs. They are bounded
exhaustive implementation validation. The formal argument above is the reason
UNSAT implies sound replacement; the tests support that the implementation
matches the argument on a large finite space.

## Thesis-Safe Claim

Safe wording:

```text
Algorithm 10 accepts a stuck-at replacement only after a SAT proof obligation
returns UNSAT in a sound proof tier. The global, TFI, cone, and audited-window
encodings were validated against brute-force truth-table semantics on bounded
exhaustive AIG spaces, and all reported benchmark outputs were independently
checked by ABC CEC.
```

Unsafe wording:

```text
The implementation is proven 100 percent correct for all circuits.
```

That stronger claim would require a fully formal machine-checked proof of the
implementation or a much more restricted theorem statement.

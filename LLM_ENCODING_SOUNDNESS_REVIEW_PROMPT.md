# Prompt For External Review Of Encoding Soundness

Act as a senior researcher in Electronic Design Automation, SAT solving, ATPG,
and combinational equivalence checking. Review the following SAT-based
redundancy-removal architecture for possible soundness holes, missing test
cases, and thesis-defense risks.

The tool operates on combinational AIG/AAG circuits. Latches, if present, are
treated as cut boundaries by comparing latch-next functions together with
primary outputs. For each AND gate candidate, the tool considers stuck-at-0 and
stuck-at-1 replacements. A candidate may be removed only if a SAT miter proves
that the faulty circuit cannot differ from the good circuit at any observable
root. SAT means an observable counterexample exists and the candidate is
rejected. Timeout means unresolved. Simulation and counterexample pruning are
rejection-only and never prove redundancy.

The final architecture contains several proof tiers: TFI constancy checks,
audited bounded TFO windows, exact affected-output cone miters, grouped cone
miters, global configurable-fault miters, and exact candidate-local TFO miters.
The exact TFO miter computes the affected observable roots from the candidate's
transitive fanout, builds the good fanin cone for those roots, duplicates only
the faulty TFO slice, and reuses good-circuit values for side inputs outside
the faulty slice. A closure audit checks that every required faulty dependency
is present and that affected roots are covered. Worker UNSAT results are
treated only as proposals; a coordinator sequentially rechecks the proposal,
rewrites one candidate, regenerates the frontier, and requires ABC CEC before
saving the new optimized AAG.

Current validation evidence includes bounded exhaustive truth-table checks for
small AIG spaces, exact TFO tests against truth-table semantics, TFO-vs-full
cone/global agreement, read-only serial/parallel worker agreement, negative
corruption controls, and repository scans showing zero CEC-failed commits in
modern dynamic/native TFO summaries.

Please answer these questions:

1. Is the UNSAT acceptance condition sound under the stated observable-root
   boundary?
2. Are good-value side inputs outside the faulty TFO slice safe, or can they
   hide a propagation path?
3. Is the TFO closure audit sufficient in principle? What dependency or
   reconvergence cases should be added to tests?
4. Does treating worker UNSAT as a proposal and requiring coordinator recheck
   plus final CEC close the main parallel-staleness risks?
5. What additional negative controls would make this thesis defense stronger?
6. How should the thesis phrase the relationship between SAT proof and ABC CEC
   so that CEC is presented as an independent audit rather than a substitute
   for a correct encoding?
7. Which stress tests should be shown in the evaluation chapter, and which
   should remain engineering validation?

Please focus on concrete soundness risks and testable recommendations. Avoid
general encouragement.

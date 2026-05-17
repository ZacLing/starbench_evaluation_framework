# Rubric Reader-Fairness

This document defines reader-fairness for make-better rubrics in Starbench-HSW tasks.

## Overall Definition

A make-better rubric is reader-fair when the requirement it evaluates can be derived by an independent agent from the task prompt, the provided materials, and relevant domain knowledge or logic. The requirement does not need to be explicitly stated in the prompt. It may be a high-seniority expectation, a subtle professional judgment, or a best-practice control, as long as it is a reasonable inference from the information available to the agent.

The standard is similar to "fair play" in detective fiction: the reader may need to reason deeply, connect clues, and apply expertise, but the solution should not depend on hidden facts, private preferences, or unrelated information that the reader could not reasonably infer.

Therefore, a rubric should not be rejected merely because it is difficult, senior-level, or absent as literal prompt wording. It should be questioned when it depends on information asymmetry, hidden expert context, or requirements unrelated to the stated task.

When a rubric is in a gray area, reviewers should ask whether a strong domain expert could explain why the requirement follows from the prompt and materials. If the answer is yes, the rubric can usually be treated as fair. If the explanation requires private knowledge that was never available to the executor, the rubric should be revised or removed.

## Review Questions

Use the following questions to evaluate whether a rubric is reader-fair.

## 1. Task Relevance

- Does the rubric evaluate something connected to the task goal, deliverable, role, audience, or constraints?
- Would satisfying the rubric make the deliverable meaningfully better for the stated user or stakeholder?
- Is the requirement about the requested task, rather than an adjacent topic the expert happens to care about?
- If the rubric is highly specific, is that specificity justified by the task context?

## 2. Derivability From Available Information

- Can the requirement be inferred from the prompt, materials, or task framing?
- Can the requirement be inferred through ordinary or advanced domain knowledge relevant to the task?
- Does the rubric require facts, preferences, definitions, or assumptions that were not available to the agent?
- Would two strong practitioners in the domain recognize the requirement as a reasonable expectation, even if they might not both include it?

## 3. Hidden Information Check

- Does the rubric depend on private expert comments, intermediate trace details, or feedback not exposed to the executor?
- Does it require knowing the expert's intended answer rather than reasoning from the task?
- Does it penalize the agent for not using a specific private formulation when an equivalent solution would satisfy the task?
- If the rubric mentions a concrete detail, was that detail present in the prompt/materials, introduced by the agent's own output, or reasonably inferable from the domain?

## 4. Seniority Versus Unfairness

- Is the requirement hard because it reflects senior judgment, or hard because the necessary information was hidden?
- Can the requirement be explained as a professional best practice, risk control, tradeoff, decomposition, or failure-mode analysis?
- Would the rubric distinguish a senior deliverable from a junior but plausible deliverable?
- Is the expected reasoning path available, even if only a strong agent is likely to find it?

## 5. Scope And Non-Arbitrariness

- Is the rubric scoped to the task rather than requiring exhaustive coverage of every possible best practice?
- Does the rubric avoid turning one expert's preferred implementation style into the only acceptable answer?
- Could a different but substantively equivalent approach pass the rubric?
- If the rubric lists examples, are they examples of acceptable coverage rather than a mandatory complete checklist?

## 6. Evidence And Evaluability

- Can an evaluator reliably determine whether the deliverable satisfies the rubric from the output and trace?
- Does the rubric ask for observable evidence rather than an uncheckable intention?
- Is the pass/fail boundary clear enough that two evaluators would usually agree?
- If the rubric is broad, does it identify the concrete behavior or artifact that should count as satisfying it?

## 7. Conditionality

- Should the rubric apply only if the agent introduces a certain topic, assumption, section, or claim?
- If the task does not require a detail to appear, is the rubric written conditionally rather than forcing every agent to introduce it?
- Does the rubric penalize mishandling of an introduced detail, rather than requiring all agents to include that detail?
- Would a correct concise answer fail only because it omitted an optional branch?

## 8. Gray-Area Resolution

For gray-area rubrics, prefer keeping the rubric when:

- The requirement follows from the task through domain expertise or logic.
- The requirement captures a meaningful senior-junior gap.
- The expert can give a clear, non-private explanation for why the requirement matters.
- The rubric can be rewritten to reduce over-specificity while preserving the senior insight.

Prefer revising or removing the rubric when:

- The requirement depends on hidden information or private expert intent.
- The requirement is unrelated to the user's requested deliverable.
- The rubric demands an exact checklist where equivalent approaches should pass.
- The rubric turns a merely optional enhancement into a universal requirement without justification.

## Practical Rule

Ask: "Could an independent strong agent, seeing only the prompt and materials, reasonably infer that this requirement matters for producing a senior-quality answer?"

If yes, the rubric is reader-fair even if it is difficult or high-level. If no, the rubric likely needs to be revised, made conditional, or removed.

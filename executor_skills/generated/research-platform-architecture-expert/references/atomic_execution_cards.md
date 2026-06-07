# Expert-level Atomic Execution Cards

## Card 1: Frame The Deliverable At The Right Level

Work type: `task_framing`
Evidence: generalized from source traces, human references, and rubrics; task-specific examples are isolated in `references/specializations/`.

Trigger:
- Use at the start of any technical-proposal task with explicit deliverable, audience, language, or section requirements.

Action:
- Identify the true work product, required structure, intended decision audience, non-goals, and minimum viable scope before drafting.

Placement:
- Executive summary and task framing

Observable evidence:
- The opening and structure make clear what is being designed, who will use it, what it will not do, and where each requested topic is answered.

Common miss:
- Writing a polished essay or broad proposal without obeying the requested structure, audience, or non-goals.

Overuse guard:
- Do not add extra governance scaffolding when the task asks for a narrow implementation or code change.

## Card 2: Define Platform Boundary And Interaction Model

Work type: `platform_boundary`
Evidence: generalized from source traces, human references, and rubrics; task-specific examples are isolated in `references/specializations/`.

Trigger:
- Use when the deliverable proposes a platform, workflow, tool, or reusable research process.

Action:
- State the platform's physical form, user interaction model, responsibilities, excluded responsibilities, and tradeoffs between MVP and full system.

Placement:
- Platform scope and user interaction

Observable evidence:
- A reader can tell whether this is a notebook/script package, web app, workflow service, governance gate, reporting layer, or production system.

Common miss:
- Describing modules and architecture while leaving engineers and users unable to picture how the platform is actually used.

Overuse guard:
- Keep the platform form proportional to the task; do not force a full product architecture onto a lightweight research workflow.

## Card 3: Govern Data Lineage, Timing, Missingness, And Comparability

Work type: `data_governance`
Evidence: generalized from source traces, human references, and rubrics; task-specific examples are isolated in `references/specializations/`.

Trigger:
- Use when empirical data, vendor feeds, market data, accounting variables, panels, or constructed datasets determine the validity of the result.

Action:
- Define data source, point-in-time availability, lineage, versioning, missingness, sample comparability, reconciliation, and blocking rules for unusable data.

Placement:
- Data governance and comparability

Observable evidence:
- The deliverable explains when data are valid, comparable, stale, missing, biased, or blocked from downstream interpretation.

Common miss:
- Listing data risks without rules that stop, downgrade, or separately disclose invalid comparisons.

Overuse guard:
- Avoid importing domain-specific data quirks unless the task domain calls for them; place those in specializations.

## Card 4: Separate Exploration, Confirmation, And Robustness

Work type: `validation_design`
Evidence: generalized from source traces, human references, and rubrics; task-specific examples are isolated in `references/specializations/`.

Trigger:
- Use when a method, factor, proxy, or platform claim needs evidence before adoption or publication.

Action:
- Separate exploratory search from frozen confirmatory tests, define windows or scenarios, require failed-result logging, and specify quantitative success metrics.

Placement:
- Validation and evaluation design

Observable evidence:
- The deliverable shows what is exploratory, what is frozen, how success is measured, and how failed or insignificant attempts are recorded.

Common miss:
- Reporting only the best-looking result or saying 'run robustness checks' without a frozen design and failure log.

Overuse guard:
- Do not imply confirmatory validity when only exploratory evidence is feasible.

## Card 5: Control Outcome-driven Selection

Work type: `selection_control`
Evidence: generalized from source traces, human references, and rubrics; task-specific examples are isolated in `references/specializations/`.

Trigger:
- Use when researchers can choose methods, parameters, proxies, filters, benchmarks, or reporting paths after seeing results.

Action:
- Require locked configurations, timestamps, hashes or version ids, amendment logs, exploratory labels, complete disclosure, and escalation for conflicts.

Placement:
- Research governance and selection control

Observable evidence:
- The deliverable prevents result shopping by making choices, changes, and exclusions visible before conclusions are accepted.

Common miss:
- Using governance words while leaving researcher discretion unconstrained after results are visible.

Overuse guard:
- For pure implementation tasks, keep this as a lightweight change log rather than a full preregistration system.

## Card 6: Design Audit, Compliance, And External Evidence Packages

Work type: `compliance_audit`
Evidence: generalized from source traces, human references, and rubrics; task-specific examples are isolated in `references/specializations/`.

Trigger:
- Use when the platform must support internal review, publication, external stakeholders, compliance, or legal constraints.

Action:
- Define audit artifacts, privacy controls, access roles, retention rules, external/internal package distinctions, and reviewer-facing summaries.

Placement:
- Audit, compliance, and reviewer evidence

Observable evidence:
- The deliverable makes clear what evidence is stored, who can see it, and how it can be shared externally.

Common miss:
- Treating audit as a log dump rather than a curated, permissioned, reviewer-usable evidence package.

Overuse guard:
- Do not add legal claims beyond available task context; flag where specialist review is needed.

## Card 7: Phase Work With Resources And Stop Points

Work type: `roadmap_resources`
Evidence: generalized from source traces, human references, and rubrics; task-specific examples are isolated in `references/specializations/`.

Trigger:
- Use when a proposal needs implementation planning or organizational adoption.

Action:
- Break the work into phases with deliverables, teams, success criteria, costs, permissions, and explicit stop/pause points.

Placement:
- Implementation roadmap and resources

Observable evidence:
- The roadmap can be reviewed stage-by-stage and does not require approving the full vision up front.

Common miss:
- Writing a timeline of activities without decision gates or resource realism.

Overuse guard:
- Avoid over-detailed project management when the task only asks for conceptual analysis.

## Card 8: Define Success, Downgrade, Pause, And Exit Criteria

Work type: `success_exit`
Evidence: generalized from source traces, human references, and rubrics; task-specific examples are isolated in `references/specializations/`.

Trigger:
- Use when the proposal asks whether to build, adopt, promote, publish, or continue investing in a platform or method.

Action:
- Set quantitative and qualitative thresholds for success, downgrade, pause, escalation, and exit.

Placement:
- Success standards and exit conditions

Observable evidence:
- The deliverable enables a decision-maker to stop, continue, or downgrade without relying on vibes.

Common miss:
- Saying 'continue if useful' or 'stop if costs exceed benefits' without measurable red lines.

Overuse guard:
- Choose thresholds that match available evidence and avoid false precision.

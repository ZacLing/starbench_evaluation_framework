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

## Card 3: Phase Work With Resources And Stop Points

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

## Card 4: Define Success, Downgrade, Pause, And Exit Criteria

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

## Card 5: Design Audit, Compliance, And External Evidence Packages

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

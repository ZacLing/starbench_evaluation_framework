from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from starbench.skills.registry import write_registry_entry


@dataclass(frozen=True)
class SourceTask:
    task_root: Path
    task_package: Path
    trace_dir: Path
    task_id: str
    task_name: str
    prompt_text: str
    rubrics: List[Dict[str, Any]]
    human_steps: List[Dict[str, Any]]
    reviews: List[Dict[str, Any]]


@dataclass(frozen=True)
class WorkType:
    id: str
    title: str
    keywords: tuple[str, ...]
    trigger: str
    action: str
    observable_evidence: str
    common_miss: str
    overuse_guard: str
    placement: str


@dataclass(frozen=True)
class ExpertArchetype:
    id: str
    title: str
    description: str
    groups: tuple[str, ...]
    work_type_ids: tuple[str, ...]
    infer_keywords: tuple[str, ...]
    excluded_scope: str


@dataclass(frozen=True)
class GeneralizedCard:
    title: str
    work_type_id: str
    trigger: str
    action: str
    placement: str
    observable_evidence: str
    common_miss: str
    overuse_guard: str
    source_task_ids: List[str]
    source_kinds: List[str]
    specializations: List[str]


TASK_SPECIFIC_TERMS = (
    "rsj",
    "realized variance",
    "rv",
    "上半方差",
    "下半方差",
    "日内",
    "intraday",
    "bar",
    "tick",
    "除权除息",
    "corporate action",
    "pls",
    "pls-sem",
    "pca",
    "cfa",
    "sem",
    "proxy",
    "latent",
    "潜变量",
    "形成式",
    "反映式",
    "accounting",
    "会计",
    "dependent variable",
    "结果变量",
)


WORK_TYPES: Dict[str, WorkType] = {
    "task_framing": WorkType(
        id="task_framing",
        title="Frame The Deliverable At The Right Level",
        keywords=("section", "markdown", "交付", "章节", "执行摘要", "conclusion", "prompt", "任务"),
        trigger="Use at the start of any technical-proposal task with explicit deliverable, audience, language, or section requirements.",
        action="Identify the true work product, required structure, intended decision audience, non-goals, and minimum viable scope before drafting.",
        observable_evidence="The opening and structure make clear what is being designed, who will use it, what it will not do, and where each requested topic is answered.",
        common_miss="Writing a polished essay or broad proposal without obeying the requested structure, audience, or non-goals.",
        overuse_guard="Do not add extra governance scaffolding when the task asks for a narrow implementation or code change.",
        placement="Executive summary and task framing",
    ),
    "platform_boundary": WorkType(
        id="platform_boundary",
        title="Define Platform Boundary And Interaction Model",
        keywords=("platform", "平台", "physical", "user interaction", "web", "workflow", "replacement", "工具"),
        trigger="Use when the deliverable proposes a platform, workflow, tool, or reusable research process.",
        action="State the platform's physical form, user interaction model, responsibilities, excluded responsibilities, and tradeoffs between MVP and full system.",
        observable_evidence="A reader can tell whether this is a notebook/script package, web app, workflow service, governance gate, reporting layer, or production system.",
        common_miss="Describing modules and architecture while leaving engineers and users unable to picture how the platform is actually used.",
        overuse_guard="Keep the platform form proportional to the task; do not force a full product architecture onto a lightweight research workflow.",
        placement="Platform scope and user interaction",
    ),
    "derived_variable_contract": WorkType(
        id="derived_variable_contract",
        title="Define Derived Research Variable Contract",
        keywords=("factor", "signal", "proxy", "score", "construct", "variable", "formula", "rsj", "因子", "指标", "构念", "变量", "公式"),
        trigger="Use when the task introduces any factor, signal, proxy, score, metric, latent construct, or derived research variable.",
        action="Specify the exact construction formula or algorithm, input fields, timestamp policy, valid sample rules, missing-data behavior, invalid-output behavior, and reproducibility checks.",
        observable_evidence="A reader can implement, audit, or reject the variable without guessing hidden parameters or boundary-condition behavior.",
        common_miss="Naming the variable and giving intuition while leaving formula, boundary conditions, lineage, or invalid-output handling implicit.",
        overuse_guard="For tasks that only ask for high-level strategy, summarize the contract requirements instead of over-specifying formulas.",
        placement="Method, factor, or measurement definition",
    ),
    "data_governance": WorkType(
        id="data_governance",
        title="Govern Data Lineage, Timing, Missingness, And Comparability",
        keywords=("data", "missing", "sample", "lineage", "timestamp", "coverage", "reconciliation", "数据", "缺失", "样本", "血缘", "时间戳", "覆盖率"),
        trigger="Use when empirical data, vendor feeds, market data, accounting variables, panels, or constructed datasets determine the validity of the result.",
        action="Define data source, point-in-time availability, lineage, versioning, missingness, sample comparability, reconciliation, and blocking rules for unusable data.",
        observable_evidence="The deliverable explains when data are valid, comparable, stale, missing, biased, or blocked from downstream interpretation.",
        common_miss="Listing data risks without rules that stop, downgrade, or separately disclose invalid comparisons.",
        overuse_guard="Avoid importing domain-specific data quirks unless the task domain calls for them; place those in specializations.",
        placement="Data governance and comparability",
    ),
    "validation_design": WorkType(
        id="validation_design",
        title="Separate Exploration, Confirmation, And Robustness",
        keywords=("validation", "backtest", "simulation", "pre-registration", "window", "robust", "mse", "bias", "验证", "回测", "模拟", "稳健", "预注册"),
        trigger="Use when a method, factor, proxy, or platform claim needs evidence before adoption or publication.",
        action="Separate exploratory search from frozen confirmatory tests, define windows or scenarios, require failed-result logging, and specify quantitative success metrics.",
        observable_evidence="The deliverable shows what is exploratory, what is frozen, how success is measured, and how failed or insignificant attempts are recorded.",
        common_miss="Reporting only the best-looking result or saying 'run robustness checks' without a frozen design and failure log.",
        overuse_guard="Do not imply confirmatory validity when only exploratory evidence is feasible.",
        placement="Validation and evaluation design",
    ),
    "selection_control": WorkType(
        id="selection_control",
        title="Control Outcome-driven Selection",
        keywords=("leakage", "dependent", "selection", "pre-register", "hash", "amendment", "disclosure", "结果变量", "泄漏", "选择", "哈希", "披露"),
        trigger="Use when researchers can choose methods, parameters, proxies, filters, benchmarks, or reporting paths after seeing results.",
        action="Require locked configurations, timestamps, hashes or version ids, amendment logs, exploratory labels, complete disclosure, and escalation for conflicts.",
        observable_evidence="The deliverable prevents result shopping by making choices, changes, and exclusions visible before conclusions are accepted.",
        common_miss="Using governance words while leaving researcher discretion unconstrained after results are visible.",
        overuse_guard="For pure implementation tasks, keep this as a lightweight change log rather than a full preregistration system.",
        placement="Research governance and selection control",
    ),
    "method_taxonomy": WorkType(
        id="method_taxonomy",
        title="Separate Method Labels From Implementations",
        keywords=("method", "pls", "sem", "pca", "cfa", "proxy", "算法", "方法", "标签", "实现"),
        trigger="Use when the task compares methods, algorithms, measurement approaches, or model families.",
        action="Define each method's role, assumptions, applicability pre-checks, implementation evidence, failure modes, and non-comparable cases.",
        observable_evidence="A reviewer can see why each method is valid, invalid, approximate, non-comparable, or mislabeled.",
        common_miss="Treating method names as interchangeable labels without checking what algorithm or implementation actually ran.",
        overuse_guard="Do not turn a single-method task into a broad taxonomy unless comparison or governance is requested.",
        placement="Method taxonomy and applicability",
    ),
    "cost_capacity": WorkType(
        id="cost_capacity",
        title="Make Feasibility Survive Costs And Capacity",
        keywords=("cost", "liquidity", "capacity", "slippage", "impact", "turnover", "成本", "流动性", "容量", "滑点", "冲击", "换手"),
        trigger="Use when research outputs could influence trading, deployment, scaling, or resource allocation.",
        action="Model fixed and variable costs, nonlinear impact, capacity, stress scenarios, and sensitivity curves before promotion.",
        observable_evidence="The deliverable includes cost-after-performance and capacity evidence rather than paper-only attractiveness.",
        common_miss="Acknowledging costs in a risk list while leaving assumptions, functions, and thresholds unspecified.",
        overuse_guard="Skip trading-specific cost details for non-financial empirical measurement tasks.",
        placement="Cost, liquidity, capacity, and feasibility",
    ),
    "monitoring_failure_gates": WorkType(
        id="monitoring_failure_gates",
        title="Define Monitoring, Escalation, Pause, And Exit Gates",
        keywords=("monitor", "decay", "crowd", "alert", "exit", "pause", "failure", "监控", "衰减", "拥挤", "告警", "退出", "停止"),
        trigger="Use when a platform output can degrade, conflict, become invalid, or require ongoing governance after initial evaluation.",
        action="Define live or periodic metrics, warning thresholds, escalation owners, pause rules, archive/re-entry criteria, and exit conditions.",
        observable_evidence="The deliverable says exactly what signal turns yellow or red, who reviews it, and what happens next.",
        common_miss="Saying 'monitor after launch' without concrete thresholds or governance actions.",
        overuse_guard="Keep monitoring cadence proportional to impact and available data freshness.",
        placement="Monitoring and failure gates",
    ),
    "research_production_consistency": WorkType(
        id="research_production_consistency",
        title="Preserve Research-to-production Consistency",
        keywords=("production", "code", "container", "ci", "regression", "benchmark dataset", "生产", "代码", "镜像", "回归测试", "基准数据集"),
        trigger="Use when research code, platform implementation, or production systems might diverge.",
        action="Require shared implementations or verifiable exports, versioned code, containers, regression tests, benchmark datasets, and acceptance tolerances.",
        observable_evidence="The deliverable prevents a research result from being promoted unless implementation parity is testable.",
        common_miss="Assuming engineers can rewrite research logic later without changing outputs.",
        overuse_guard="Use a lighter reproducibility check when no production handoff is involved.",
        placement="Engineering reproducibility",
    ),
    "compliance_audit": WorkType(
        id="compliance_audit",
        title="Design Audit, Compliance, And External Evidence Packages",
        keywords=("audit", "reviewer", "compliance", "license", "retention", "appendix", "审计", "审稿", "合规", "授权", "留存", "附录"),
        trigger="Use when the platform must support internal review, publication, external stakeholders, compliance, or legal constraints.",
        action="Define audit artifacts, privacy controls, access roles, retention rules, external/internal package distinctions, and reviewer-facing summaries.",
        observable_evidence="The deliverable makes clear what evidence is stored, who can see it, and how it can be shared externally.",
        common_miss="Treating audit as a log dump rather than a curated, permissioned, reviewer-usable evidence package.",
        overuse_guard="Do not add legal claims beyond available task context; flag where specialist review is needed.",
        placement="Audit, compliance, and reviewer evidence",
    ),
    "roadmap_resources": WorkType(
        id="roadmap_resources",
        title="Phase Work With Resources And Stop Points",
        keywords=("roadmap", "phase", "mvp", "resource", "cost", "maintenance", "路线图", "阶段", "资源", "维护"),
        trigger="Use when a proposal needs implementation planning or organizational adoption.",
        action="Break the work into phases with deliverables, teams, success criteria, costs, permissions, and explicit stop/pause points.",
        observable_evidence="The roadmap can be reviewed stage-by-stage and does not require approving the full vision up front.",
        common_miss="Writing a timeline of activities without decision gates or resource realism.",
        overuse_guard="Avoid over-detailed project management when the task only asks for conceptual analysis.",
        placement="Implementation roadmap and resources",
    ),
    "success_exit": WorkType(
        id="success_exit",
        title="Define Success, Downgrade, Pause, And Exit Criteria",
        keywords=("success", "exit", "threshold", "pause", "stop", "downgrade", "成功", "退出", "阈值", "暂停", "降级"),
        trigger="Use when the proposal asks whether to build, adopt, promote, publish, or continue investing in a platform or method.",
        action="Set quantitative and qualitative thresholds for success, downgrade, pause, escalation, and exit.",
        observable_evidence="The deliverable enables a decision-maker to stop, continue, or downgrade without relying on vibes.",
        common_miss="Saying 'continue if useful' or 'stop if costs exceed benefits' without measurable red lines.",
        overuse_guard="Choose thresholds that match available evidence and avoid false precision.",
        placement="Success standards and exit conditions",
    ),
}


ARCHETYPES: Dict[str, ExpertArchetype] = {
    "senior-technical-proposal-expert": ExpertArchetype(
        id="senior-technical-proposal-expert",
        title="Senior Technical Proposal Expert",
        description=(
            "Use when executing senior technical-proposal tasks that require correct task framing, stakeholder-aware "
            "structure, scoped MVP choices, risk-to-control mapping, implementation roadmap, resource realism, "
            "success criteria, and final coverage checks. Provides private planning and proposal-quality guidance."
        ),
        groups=("senior-expert-core",),
        work_type_ids=("task_framing", "platform_boundary", "roadmap_resources", "success_exit", "compliance_audit"),
        infer_keywords=("proposal", "technical plan", "技术方案", "路线图", "stakeholder", "受众"),
        excluded_scope="Does not provide deep domain formulas or specialized statistical/finance methods unless paired with a domain expert skill.",
    ),
    "research-platform-architecture-expert": ExpertArchetype(
        id="research-platform-architecture-expert",
        title="Research Platform Architecture Expert",
        description=(
            "Use when executing tasks about reusable research platforms, evaluation workflows, governance gates, "
            "auditability, reproducibility, stakeholder outputs, implementation phasing, and long-term maintenance. "
            "Provides private senior architecture guidance for turning a research idea into an operable platform."
        ),
        groups=("research-platforms", "senior-expert-core"),
        work_type_ids=(
            "task_framing",
            "platform_boundary",
            "data_governance",
            "validation_design",
            "selection_control",
            "compliance_audit",
            "roadmap_resources",
            "success_exit",
        ),
        infer_keywords=("platform", "平台", "governance", "治理", "audit", "审计", "workflow", "reusable"),
        excluded_scope="Does not by itself supply market-microstructure or measurement-model specialties; load a domain expert when needed.",
    ),
    "quant-finance-research-platform-expert": ExpertArchetype(
        id="quant-finance-research-platform-expert",
        title="Quant Finance Research Platform Expert",
        description=(
            "Use when executing quantitative-finance research platform tasks involving alpha or factor definition, "
            "market-data quality, backtest validity, point-in-time controls, cost and capacity modeling, production "
            "readiness gates, monitoring, compliance, and research-to-production promotion decisions."
        ),
        groups=("quant-finance", "research-platforms"),
        work_type_ids=(
            "task_framing",
            "platform_boundary",
            "derived_variable_contract",
            "data_governance",
            "validation_design",
            "selection_control",
            "cost_capacity",
            "monitoring_failure_gates",
            "research_production_consistency",
            "compliance_audit",
            "roadmap_resources",
            "success_exit",
        ),
        infer_keywords=("factor", "alpha", "portfolio", "backtest", "rsj", "intraday", "market", "trading", "liquidity", "量化", "因子", "回测", "交易", "流动性"),
        excluded_scope="Does not cover non-financial latent-construct methodology except at the generic research-platform level.",
    ),
    "empirical-measurement-governance-expert": ExpertArchetype(
        id="empirical-measurement-governance-expert",
        title="Empirical Measurement Governance Expert",
        description=(
            "Use when executing empirical-research platform tasks involving latent constructs, proxy construction, "
            "measurement-method comparison, preregistration, dependent-variable leakage, sample comparability, "
            "method applicability, audit artifacts, and reviewer-facing evidence packages."
        ),
        groups=("empirical-measurement", "research-platforms"),
        work_type_ids=(
            "task_framing",
            "platform_boundary",
            "derived_variable_contract",
            "data_governance",
            "validation_design",
            "selection_control",
            "method_taxonomy",
            "compliance_audit",
            "roadmap_resources",
            "success_exit",
        ),
        infer_keywords=("latent", "proxy", "measurement", "pls", "sem", "construct", "accounting", "dependent variable", "潜变量", "测量", "会计", "构念"),
        excluded_scope="Does not provide trading-cost, capacity, or market-microstructure production checks unless paired with a quant finance expert.",
    ),
}


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "executor-skill"


def sentence_trim(text: str, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def strip_rubric_question(question: str) -> str:
    text = question.strip()
    replacements = [
        (r"^Does the deliverable\s+", ""),
        (r"^When the research involves panel data,\s*does the deliverable\s+", "When panel data is involved, "),
        (r"^交付物是否", ""),
        (r"\?$", ""),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text.strip(" ?？")


def resolve_source_task(path: Path) -> SourceTask:
    path = path.resolve()
    if path.name == "task_package":
        task_package = path
        task_root = path.parent
    elif (path / "task_package").exists():
        task_root = path
        task_package = path / "task_package"
    elif (path / "task.json").exists():
        task_package = path
        task_root = path.parent
    else:
        raise FileNotFoundError(f"Cannot find task_package for source task: {path}")

    trace_dir = task_root / "trace"
    task_config = json.loads((task_package / "task.json").read_text(encoding="utf-8"))
    prompt_path = task_package / task_config.get("prompt", "prompt.md")
    rubrics_path = task_package / task_config.get("rubrics", "rubrics.json")
    human_reference_path = task_package / task_config.get("human_reference", "human_reference.json")
    prompt_text = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
    rubrics = json.loads(rubrics_path.read_text(encoding="utf-8")).get("rubrics", [])
    human_steps: List[Dict[str, Any]] = []
    if human_reference_path.exists():
        human_steps = json.loads(human_reference_path.read_text(encoding="utf-8")).get("steps", [])

    reviews: List[Dict[str, Any]] = []
    reviews_dir = trace_dir / "reviews"
    if reviews_dir.exists():
        for review_path in sorted(reviews_dir.glob("r*_review/review.json")):
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["_path"] = str(review_path)
            reviews.append(review)

    return SourceTask(
        task_root=task_root,
        task_package=task_package,
        trace_dir=trace_dir,
        task_id=str(task_config["id"]),
        task_name=str(task_config.get("name", task_config["id"])),
        prompt_text=prompt_text,
        rubrics=rubrics,
        human_steps=human_steps,
        reviews=reviews,
    )


def parse_raw_weaknesses(raw_text: str) -> List[str]:
    if not raw_text:
        return []
    match = re.search(
        r"Weaknesses\s*(.*?)(?:Latest Deliverables Satisfaction|Notes\s*$|\Z)",
        raw_text,
        re.DOTALL | re.IGNORECASE,
    )
    body = match.group(1) if match else raw_text
    chunks = re.split(r"\n\s*(?:弱点\s*)?\d+[\.、:：]\s*", body)
    weaknesses = []
    for chunk in chunks:
        chunk = re.sub(r"\n+", "\n", chunk.strip())
        if len(chunk) >= 20:
            weaknesses.append(sentence_trim(chunk, 700))
    return weaknesses


def iter_review_weaknesses(task: SourceTask) -> Iterable[tuple[str, str]]:
    for review in task.reviews:
        review_id = str(review.get("review_id", "review"))
        structured = [str(item) for item in review.get("weaknesses", []) if str(item).strip()]
        weaknesses = structured or parse_raw_weaknesses(str(review.get("raw_text", "")))
        for weakness in weaknesses:
            yield review_id, weakness


def source_texts(task: SourceTask) -> List[tuple[str, str]]:
    texts: List[tuple[str, str]] = [("prompt", task.prompt_text)]
    for rubric in task.rubrics:
        texts.append(("rubric", str(rubric.get("question", ""))))
    for step in task.human_steps:
        texts.append(("human_reference", f"{step.get('instruction', '')} {step.get('reasoning', '')}"))
    for review_id, weakness in iter_review_weaknesses(task):
        texts.append((f"trace:{review_id}", weakness))
    return texts


def combined_corpus(tasks: Sequence[SourceTask]) -> str:
    return "\n".join(text for task in tasks for _, text in source_texts(task)).lower()


def infer_archetype(tasks: Sequence[SourceTask]) -> ExpertArchetype:
    corpus = combined_corpus(tasks)
    scored = []
    for archetype in ARCHETYPES.values():
        score = sum(1 for keyword in archetype.infer_keywords if keyword.lower() in corpus)
        scored.append((score, archetype.id, archetype))
    scored.sort(reverse=True)
    return scored[0][2] if scored and scored[0][0] > 0 else ARCHETYPES["research-platform-architecture-expert"]


def get_archetype(archetype_id: str | None, tasks: Sequence[SourceTask]) -> ExpertArchetype:
    if archetype_id:
        key = slugify(archetype_id)
        if key not in ARCHETYPES:
            raise ValueError(f"Unknown expert archetype {archetype_id!r}. Known: {', '.join(sorted(ARCHETYPES))}")
        return ARCHETYPES[key]
    return infer_archetype(tasks)


def task_specific_terms(text: str) -> List[str]:
    lower = text.lower()
    terms = []
    for term in TASK_SPECIFIC_TERMS:
        if term.lower() in lower and term not in terms:
            terms.append(term)
    return terms


def match_work_type(text: str, work_type: WorkType) -> bool:
    lower = text.lower()
    return any(keyword.lower() in lower for keyword in work_type.keywords)


def collect_work_type_evidence(tasks: Sequence[SourceTask], work_type: WorkType) -> tuple[List[str], List[str], List[str]]:
    source_task_ids: List[str] = []
    source_kinds: List[str] = []
    specializations: List[str] = []
    for task in tasks:
        for kind, text in source_texts(task):
            if not text or not match_work_type(text, work_type):
                continue
            if task.task_id not in source_task_ids:
                source_task_ids.append(task.task_id)
            if kind not in source_kinds:
                source_kinds.append(kind)
            terms = task_specific_terms(text)
            if terms:
                specializations.append(
                    f"`{task.task_id}` shows this through {', '.join(terms[:8])}: {sentence_trim(strip_rubric_question(text), 220)}"
                )
    return source_task_ids, source_kinds, specializations


def build_generalized_cards(tasks: Sequence[SourceTask], archetype: ExpertArchetype) -> List[GeneralizedCard]:
    cards: List[GeneralizedCard] = []
    for work_type_id in archetype.work_type_ids:
        work_type = WORK_TYPES[work_type_id]
        source_task_ids, source_kinds, specializations = collect_work_type_evidence(tasks, work_type)
        if not source_task_ids:
            continue
        cards.append(
            GeneralizedCard(
                title=work_type.title,
                work_type_id=work_type.id,
                trigger=work_type.trigger,
                action=work_type.action,
                placement=work_type.placement,
                observable_evidence=work_type.observable_evidence,
                common_miss=work_type.common_miss,
                overuse_guard=work_type.overuse_guard,
                source_task_ids=source_task_ids,
                source_kinds=source_kinds,
                specializations=specializations[:8],
            )
        )
    return cards


def build_operating_principles(archetype: ExpertArchetype, cards: Sequence[GeneralizedCard]) -> List[Dict[str, str]]:
    principles = [
        {
            "name": "Expert Identity Before Task Vocabulary",
            "summary": "Use the senior expert's operating frame first; treat task-specific terms as examples or specializations, not as the skill identity.",
            "use_when": "Use on every activation of this skill.",
            "failure_mode": "Overfitting the response to a familiar task noun instead of solving the deeper work type.",
        },
        {
            "name": "Evidence Must Become Decision Control",
            "summary": "Data, validation, costs, governance, and audit details should change decisions, not merely decorate the proposal.",
            "use_when": "Use whenever the deliverable proposes adoption, promotion, publication, or production-readiness.",
            "failure_mode": "Listing risks without gates, thresholds, owners, or consequences.",
        },
        {
            "name": "Fine-grained Checks Serve The Expert Model",
            "summary": "Atomic cards should make senior judgment executable at the paragraph, table, threshold, and artifact level.",
            "use_when": "Use before finalizing any technical proposal.",
            "failure_mode": "Turning rubrics into a flat checklist without preserving expert-level reasoning.",
        },
    ]
    if any(card.work_type_id == "data_governance" for card in cards):
        principles.append(
            {
                "name": "Data Lineage Before Interpretation",
                "summary": "A result is only interpretable after data availability, timing, missingness, comparability, and lineage are governed.",
                "use_when": "Use whenever empirical data or constructed variables determine the result.",
                "failure_mode": "Presenting conclusions before proving that the inputs are valid and comparable.",
            }
        )
    if any(card.work_type_id == "validation_design" for card in cards):
        principles.append(
            {
                "name": "Exploration Is Not Confirmation",
                "summary": "Separate exploratory search from frozen confirmatory evaluation and disclose failed or insignificant attempts.",
                "use_when": "Use whenever methods, parameters, proxies, filters, or signals are compared.",
                "failure_mode": "Letting the best-looking result silently become the main recommendation.",
            }
        )
    return principles


def build_decision_heuristics(tasks: Sequence[SourceTask], archetype: ExpertArchetype) -> List[str]:
    heuristics: List[str] = []
    seen = set()
    for work_type_id in archetype.work_type_ids:
        work_type = WORK_TYPES[work_type_id]
        heuristic = f"If the task involves {work_type.title.lower()}, then {work_type.action}"
        if heuristic not in seen:
            heuristics.append(heuristic)
            seen.add(heuristic)
    for task in tasks:
        for step in task.human_steps:
            instruction = str(step.get("instruction", "")).strip()
            reasoning = sentence_trim(str(step.get("reasoning", "")), 220)
            if instruction:
                heuristic = f"If the source task triggers `{step.get('step_type', 'expert step')}`, generalize the expert move: {instruction} Rationale: {reasoning}"
                if heuristic not in seen:
                    heuristics.append(heuristic)
                    seen.add(heuristic)
    return heuristics


def write_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def render_skill_md(skill_id: str, title: str, archetype: ExpertArchetype, description: str) -> str:
    return f"""---
name: {skill_id}
description: |
  {description}
---

# {title}

Use this skill only as private execution guidance. Do not mention this skill, expert traces, rubrics, harnesses, or internal checklists in deliverables.

## Workflow

1. Read `./inputs/prompt.md` and all task materials first.
2. Open `references/expert_profile.md` to confirm the senior expert role and scope.
3. Use `references/workflow.md` to classify the task by work type, not by task noun.
4. Load `references/operating_principles.md` and `references/decision_heuristics.md` for senior framing.
5. Apply relevant expert-level cards from `references/atomic_execution_cards.md`.
6. Use `references/specializations/` only as examples for matching domains; do not let examples override the task prompt.
7. Run `references/section_micro_checks.md` and `references/final_self_check.md` before finishing.
8. The task prompt and materials remain authoritative if they conflict with this skill.
"""


def render_expert_profile(archetype: ExpertArchetype) -> str:
    return f"""# Expert Profile

Expert archetype: `{archetype.id}`

## Role

{archetype.description}

## Scope Boundary

{archetype.excluded_scope}

## Operating Rule

Think at the level of senior expert work types. Treat task-specific nouns as evidence and examples, not as the skill's identity.
"""


def render_workflow(archetype: ExpertArchetype) -> str:
    work_lines = "\n".join(f"- `{work_type_id}`: {WORK_TYPES[work_type_id].title}" for work_type_id in archetype.work_type_ids)
    return f"""# Workflow

## Step 1: Classify By Work Type

Choose the relevant work types before writing:

{work_lines}

## Step 2: Establish Senior Framing

- Name the decision the deliverable enables.
- Define the system, platform, method, or governance boundary.
- Identify what would make the output invalid, misleading, non-actionable, or non-promotable.

## Step 3: Convert Expert Judgment Into Deliverable Evidence

- Use atomic cards to create paragraphs, tables, thresholds, artifacts, owners, and escalation rules.
- Keep domain examples proportional and only when they match the prompt.

## Step 4: Check For Overfitting

- Remove unnecessary task-specific terms from the main argument.
- Keep specific terms in examples, specializations, or appendices.
"""


def render_operating_principles(principles: Sequence[Dict[str, str]]) -> str:
    lines = ["# Operating Principles", ""]
    for index, principle in enumerate(principles, start=1):
        lines.extend(
            [
                f"## Principle {index}: {principle['name']}",
                "",
                f"One sentence: {principle['summary']}",
                "",
                f"Use when: {principle['use_when']}",
                "",
                f"Failure mode: {principle['failure_mode']}",
                "",
            ]
        )
    return "\n".join(lines)


def render_decision_heuristics(heuristics: Sequence[str]) -> str:
    lines = ["# Decision Heuristics", ""]
    for index, heuristic in enumerate(heuristics, start=1):
        lines.append(f"{index}. {heuristic}")
    return "\n".join(lines)


def render_atomic_cards(cards: Sequence[GeneralizedCard]) -> str:
    lines = ["# Expert-level Atomic Execution Cards", ""]
    for index, card in enumerate(cards, start=1):
        lines.extend(
            [
                f"## Card {index}: {card.title}",
                "",
                f"Work type: `{card.work_type_id}`",
                "Evidence: generalized from source traces, human references, and rubrics; task-specific examples are isolated in `references/specializations/`.",
                "",
                "Trigger:",
                f"- {card.trigger}",
                "",
                "Action:",
                f"- {card.action}",
                "",
                "Placement:",
                f"- {card.placement}",
                "",
                "Observable evidence:",
                f"- {card.observable_evidence}",
                "",
                "Common miss:",
                f"- {card.common_miss}",
                "",
                "Overuse guard:",
                f"- {card.overuse_guard}",
                "",
            ]
        )
    return "\n".join(lines)


def render_section_checks(cards: Sequence[GeneralizedCard]) -> str:
    grouped: Dict[str, List[GeneralizedCard]] = {}
    for card in cards:
        grouped.setdefault(card.placement, []).append(card)
    lines = ["# Section Micro-checks", ""]
    for placement, placement_cards in grouped.items():
        lines.extend([f"## {placement}", ""])
        for card in placement_cards:
            lines.append(f"- {card.observable_evidence}")
        lines.append("")
    return "\n".join(lines)


def render_deliverable_dna(title: str) -> str:
    return f"""# Deliverable DNA

- Write as a senior {title.lower()}, not as a task-specific keyword matcher.
- Start with a conditional recommendation and clear system boundary.
- Convert important claims into definitions, thresholds, gates, artifacts, owners, or escalation rules.
- Use examples only when they clarify the current task; keep them out of the skill identity.
- Make the output usable by decision-makers, implementers, reviewers, and governance owners.
"""


def render_final_self_check() -> str:
    return """# Final Self-check

- Did the response obey the requested language, format, section count, and output path?
- Did it apply the right senior expert archetype instead of overfitting to task nouns?
- Did it define the system boundary and avoid overclaiming?
- Did it include concrete definitions, data rules, validation gates, costs, monitoring, audit artifacts, and exit criteria where relevant?
- Did vague placeholders become thresholds, artifacts, owners, or escalation consequences?
- Did domain examples stay proportional and relevant?
- Did it avoid mentioning this skill, expert traces, hidden rubrics, or internal checklists?
"""


def render_specializations(tasks: Sequence[SourceTask], cards: Sequence[GeneralizedCard]) -> Dict[str, str]:
    by_task: Dict[str, List[str]] = {task.task_id: [] for task in tasks}
    for card in cards:
        for specialization in card.specializations:
            for task_id in by_task:
                if f"`{task_id}`" in specialization:
                    by_task[task_id].append(f"- {card.title}: {specialization}")
    outputs = {}
    for task_id, items in by_task.items():
        outputs[f"{slugify(task_id)}.md"] = "# Task-specific Specialization Examples\n\n" + (
            "\n".join(items) if items else "No task-specific specializations were needed."
        )
    return outputs


def render_research_files(task: SourceTask) -> Dict[str, str]:
    weaknesses = list(iter_review_weaknesses(task))
    return {
        "01-task-intent.md": f"# Task Intent\n\nTask: `{task.task_id}`\n\n{sentence_trim(task.prompt_text, 2500)}\n",
        "02-expert-trace-weaknesses.md": "# Expert Trace Weaknesses\n\n"
        + "\n\n".join(f"## {review_id}\n\n{weakness}" for review_id, weakness in weaknesses),
        "03-human-reference.md": "# Human Reference Steps\n\n"
        + "\n\n".join(
            f"## {step.get('step_id', 'step')} {step.get('step_type', '')}\n\nInstruction: {step.get('instruction', '')}\n\nReasoning: {step.get('reasoning', '')}"
            for step in task.human_steps
        ),
        "04-rubric-requirements.md": "# Rubric-derived Requirements\n\n"
        + "\n\n".join(
            f"- fail_fast={bool(rubric.get('fail_fast'))}: {rubric.get('question', '')}"
            for rubric in task.rubrics
        ),
        "05-trace-timeline.md": "# Trace Timeline\n\n"
        + "\n".join(
            f"- {review.get('review_id', 'review')} reviewed {review.get('round_under_review', 'unknown')}"
            for review in task.reviews
        ),
        "06-source-index.md": f"# Source Index\n\n- Task root: `{task.task_root}`\n- Task package: `{task.task_package}`\n- Trace dir: `{task.trace_dir}`\n",
    }


def write_skill(
    tasks: Sequence[SourceTask],
    *,
    output_root: Path,
    skill_id: str | None = None,
    title: str | None = None,
    description: str | None = None,
    groups: Sequence[str] | None = None,
    leakage_level: str,
    expert_archetype_id: str | None = None,
) -> Path:
    archetype = get_archetype(expert_archetype_id, tasks)
    skill_id = slugify(skill_id or archetype.id)
    title = title or archetype.title
    description = description or archetype.description
    output_root = output_root.resolve()
    skill_dir = output_root / "generated" / skill_id
    if skill_dir.exists():
        shutil.rmtree(skill_dir)
    references_dir = skill_dir / "references"
    research_dir = references_dir / "research"
    specializations_dir = references_dir / "specializations"
    references_dir.mkdir(parents=True, exist_ok=True)
    specializations_dir.mkdir(parents=True, exist_ok=True)

    cards = build_generalized_cards(tasks, archetype)
    principles = build_operating_principles(archetype, cards)
    heuristics = build_decision_heuristics(tasks, archetype)
    created_at = datetime.now(timezone.utc).isoformat()
    all_groups = sorted(set(archetype.groups) | set(groups or []))

    write_markdown(skill_dir / "SKILL.md", render_skill_md(skill_id, title, archetype, description))
    write_markdown(references_dir / "expert_profile.md", render_expert_profile(archetype))
    write_markdown(references_dir / "workflow.md", render_workflow(archetype))
    write_markdown(references_dir / "operating_principles.md", render_operating_principles(principles))
    write_markdown(references_dir / "decision_heuristics.md", render_decision_heuristics(heuristics))
    write_markdown(references_dir / "atomic_execution_cards.md", render_atomic_cards(cards))
    write_markdown(references_dir / "section_micro_checks.md", render_section_checks(cards))
    write_markdown(references_dir / "deliverable_dna.md", render_deliverable_dna(title))
    write_markdown(
        references_dir / "anti_patterns.md",
        "# Anti-patterns\n\n"
        "- Skill identity copied from a task object instead of a senior expert capability.\n"
        "- Provenance or trace history placed in `description` instead of `provenance.json`.\n"
        "- Rubric paraphrases used as cards without a generalized expert action.\n"
        "- Domain examples promoted to universal rules.\n"
        "- Vague proposal language without thresholds, gates, artifacts, or owners.\n",
    )
    write_markdown(
        references_dir / "honest_boundaries.md",
        "# Honest Boundaries\n\n"
        "- This skill is private execution guidance, not an evaluator and not hidden-rubric access.\n"
        "- Source tasks provide evidence; they do not define the skill identity.\n"
        "- Specializations are examples, not universal requirements.\n"
        "- The task prompt remains authoritative.\n"
        "- Do not mention the skill or trace provenance in deliverables.\n",
    )
    write_markdown(references_dir / "final_self_check.md", render_final_self_check())

    for filename, content in render_specializations(tasks, cards).items():
        write_markdown(specializations_dir / filename, content)
    for task in tasks:
        task_research_dir = research_dir / task.task_id
        for filename, content in render_research_files(task).items():
            write_markdown(task_research_dir / filename, content)

    provenance = {
        "skill_id": skill_id,
        "title": title,
        "created_at": created_at,
        "distiller": "starbench.skill_distiller.distill",
        "method_version": "senior-expert-archetype-v2",
        "expert_archetype": {
            "id": archetype.id,
            "title": archetype.title,
            "work_type_ids": list(archetype.work_type_ids),
        },
        "leakage_level": leakage_level,
        "source_tasks": [
            {
                "task_id": task.task_id,
                "task_name": task.task_name,
                "task_root": str(task.task_root),
                "rubric_count": len(task.rubrics),
                "human_reference_step_count": len(task.human_steps),
                "review_count": len(task.reviews),
            }
            for task in tasks
        ],
        "generalized_card_count": len(cards),
        "operating_principle_count": len(principles),
        "decision_heuristic_count": len(heuristics),
        "groups": all_groups,
    }
    (skill_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    write_registry_entry(
        output_root,
        skill_id=skill_id,
        relative_path=f"generated/{skill_id}",
        activation=f"Use `{skill_id}` as private {archetype.title.lower()} guidance for this task.",
        description=description,
        leakage_level=leakage_level,
        groups=all_groups,
    )
    return skill_dir


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Distill StarBench traces and rubrics into a senior expert-level executor Codex Skill.")
    parser.add_argument("--source-task", action="append", type=Path, required=True, help="Task root or task_package path. Repeatable.")
    parser.add_argument("--output-root", type=Path, default=Path("executor_skills"), help="Shared executor skill root.")
    parser.add_argument("--expert-archetype", choices=sorted(ARCHETYPES), help="Senior expert archetype to generate. If omitted, infer from sources.")
    parser.add_argument("--skill-id", help="Generated executor skill id. Defaults to the expert archetype id.")
    parser.add_argument("--title", help="Human-readable skill title. Defaults to the archetype title.")
    parser.add_argument("--description", help="Positive activation description. Defaults to the archetype description.")
    parser.add_argument("--group", action="append", default=[], help="Additional registry group to add this skill to. Repeatable.")
    parser.add_argument("--leakage-level", default="S4-trace-and-rubric-distilled", help="Audit label for generated skill provenance.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    tasks = [resolve_source_task(path) for path in args.source_task]
    skill_dir = write_skill(
        tasks,
        output_root=args.output_root,
        skill_id=args.skill_id,
        title=args.title,
        description=args.description,
        groups=args.group,
        leakage_level=args.leakage_level,
        expert_archetype_id=args.expert_archetype,
    )
    print(json.dumps({"skill_id": skill_dir.name, "skill_dir": str(skill_dir)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""N-dimensional cross-tab compute (build plan section 8).

The core rule of this module: nesting is more slicing before the same call,
not new math. Every figure returned here comes out of the existing
``compute_question_stats`` in ``surveytool.compute.frequency``, which is
called unmodified. No netting, counting or percentaging logic is
reimplemented, and none of ``frequency.py`` / ``stats.py`` is touched. That
is what makes INV-1 (a depth-1 break reproduces the already-verified
single-break figures exactly) hold by construction rather than by
coincidence: ``compute_cross_tab`` slices ``survey.responses`` to a subgroup's
respondent ids and calls ``compute_question_stats``; this module slices to an
N-dimensional ``Cell``'s ``respondent_ids`` and calls the same function.

Suppression is applied as post-processing over an already-computed result
(build plan section 8 step 6): everything is computed first — including the
INV-6 identity assertion — and only then are ``counts``/``percentages``/
``nets`` replaced with ``None`` for a suppressed cell. Skipping the compute
for suppressed cells as an optimisation would skip the identity checks too,
so it is deliberately not done.

Nets are scoped to exactly the two the existing netting logic already
produces — ``t2b`` and ``b2b`` — and each is emitted only when the question
actually has codes in the corresponding role, mirroring
``compute_question_stats``'s own ``has_top``/``has_bottom`` gating. This
build introduces no general net system.
"""
from __future__ import annotations

import pandas as pd
from pydantic import BaseModel

from surveytool.charts.errors import ErrorCode, SurveyToolError
from surveytool.compute.frequency import compute_question_stats
from surveytool.core.cohort import Cell, apply_filter, resolve_cells
from surveytool.core.config import ToolConfig
from surveytool.core.demographic_registry import ResolvedRegistry
from surveytool.core.model import CodeRole, Question, Response, ScaleCode, Survey
from surveytool.core.suppression import Band, classify_band

# Per-point polarity derives directly from the point's existing CodeRole
# (build plan / task brief): top -> positive, bottom -> negative, neutral ->
# neutral. excluded/nonsubstantive points carry no polarity. CodeRole already
# holds this information per point, so no registry lookup is built here.
_POLARITY_BY_ROLE: dict[CodeRole, str] = {
    CodeRole.top: "positive",
    CodeRole.bottom: "negative",
    CodeRole.neutral: "neutral",
}

# The only two nets in scope for this build, each keyed to the CodeRole whose
# members constitute it and the QuestionStats attribute carrying its
# already-computed percentage.
_NET_DEFINITIONS: tuple[tuple[str, str, CodeRole], ...] = (
    ("t2b", "Top 2 Box", CodeRole.top),
    ("b2b", "Bottom 2 Box", CodeRole.bottom),
)


class ScalePoint(BaseModel):
    """One scale point of a question, in rank order (see _scale_points)."""

    code: str | int
    label: str
    order: int
    polarity: str | None
    rank: int | None = None


class NetDefinition(BaseModel):
    """A net's identity and membership, at question level (not per cell)."""

    net_id: str
    label: str
    member_codes: list[str | int]


class NetResult(BaseModel):
    """One net's figures within a single cell.

    ``percentage`` is taken verbatim from ``QuestionStats.t2b``/``.b2b`` (which
    are already percentages over ``base_valid``). ``count`` is the sum of the
    per-code counts ``compute_question_stats`` already produced for the net's
    member role — an aggregation of existing figures, not a reimplementation
    of netting.
    """

    count: int
    percentage: float
    base_valid: int


class BaseProvenancePayload(BaseModel):
    """Round A prompt A5: why base_valid is smaller than base_cell for this
    column, broken out by reason rather than collapsed to one label — each
    reason is its own field, all present at once when more than one
    applies. Mirrors surveytool.compute.stats.BaseProvenance verbatim; see
    that dataclass's docstring for why suppression and straightliner
    exclusion are deliberately not reasons carried here."""

    routed: int
    item_missing: int
    nonsubstantive_excluded: int


class ColumnResult(BaseModel):
    """One column of the cross-tab: one cell's figures for one question.

    ``significance`` and ``significance_basis`` ship now and are always
    ``None`` (build plan section 10) so v1.1 does not force a render rewrite.
    Do not populate them.
    """

    key: list[list[str]]
    label_path: list[str]
    base_cell: int
    base_valid: int | None
    n_invalid: int | None
    base_provenance: BaseProvenancePayload | None = None
    band: Band
    counts: dict[str, int] | None
    percentages: dict[str, float] | None
    nets: dict[str, NetResult] | None
    significance: None = None
    significance_basis: None = None


class QuestionResult(BaseModel):
    """One question's full N-dimensional cross-tab result.

    Matches build plan section 10 minus ``permitted_charts``, which is Task
    8's job (chart type validity, section 9). The field is declared here as an
    empty-defaulted list so this model is already payload-shaped and Task 8
    populates it rather than having to change the model's shape.
    """

    question_id: str
    question_text: str
    scale_id: str | None
    scale_variant: str | None = None
    scale_points: list[ScalePoint]
    nets: list[NetDefinition]
    base_total: int
    base_filtered: int
    columns: list[ColumnResult]
    permitted_charts: list = []
    demographic_notices: list[str] = []
    """Task 9: plain-English notes for every declared-not-collected category
    on a dimension in this result's break spec — e.g. "Age band — 'Below 18'
    was not collected by this vendor: ...". Reuses ResolvedRegistry's
    not_collected_for_vendor (the same source build_run_summary's
    demographic_gap_statement draws from) rather than a parallel
    notification mechanism, filtered down to only the dimensions actually
    broken out here so a table never carries a note about a dimension it
    doesn't display. Empty when the break spec includes no such dimension."""
    display_order_is_manual: bool = False
    """Round C3: True when this question's scale_points were ordered from
    an analyst's saved manual DisplayOrder rather than the rank-order
    default. Never affects nets/mean -- those are always computed from
    rank regardless of this flag or of scale_points' order."""


def _scale_points(question: Question, manual_label_order: list[str] | None = None) -> list[ScalePoint]:
    """Order by manual_label_order if provided (Round C3 -- an analyst's
    saved reorder), else by rank ascending (rank 1 = bottom, Round B
    default), else by original question.labels position for anything with
    no rank at all. Manual order NEVER changes which points exist or their
    role/rank/polarity -- only their display position. Never by the
    position a label happened to land at in question.labels (which for
    Milieu/Toluna is vendor-data-appearance order and carries no ordinal
    meaning -- see Round B). A code with no rank (categorical/binary/
    nonsubstantive) sorts after every ranked point, in its original
    question.labels order, since there is no ordinal position to place it
    at."""
    if manual_label_order is not None:
        order_index = {label: i for i, label in enumerate(manual_label_order)}
        ordered = sorted(
            question.labels,
            key=lambda sc: order_index.get(sc.label, len(manual_label_order)),
        )
    else:
        ranked = sorted(
            (sc for sc in question.labels if sc.rank is not None),
            key=lambda sc: sc.rank,
        )
        unranked = [sc for sc in question.labels if sc.rank is None]
        ordered = ranked + unranked
    return [
        ScalePoint(
            code=sc.code,
            label=sc.label,
            order=i,
            polarity=_POLARITY_BY_ROLE.get(sc.role),
            rank=sc.rank,
        )
        for i, sc in enumerate(ordered)
    ]


def _net_definitions(question: Question) -> list[NetDefinition]:
    """Emit a net entry only when the question actually has codes in that
    role, mirroring compute_question_stats's has_top/has_bottom gating."""
    definitions: list[NetDefinition] = []
    for net_id, label, role in _NET_DEFINITIONS:
        member_codes = [sc.code for sc in question.labels if sc.role is role]
        if not member_codes:
            continue
        definitions.append(
            NetDefinition(net_id=net_id, label=label, member_codes=member_codes)
        )
    return definitions


def _resolve_question(survey: Survey, question_id: str) -> Question:
    """Resolve a qid against the survey's questions.

    Follows the precedent set by desktop/app.py's get_cross_tab endpoint: an
    unknown qid is not user-triggerable through the normal picker (which only
    ever offers qids the loaded survey declares), so it is an INTERNAL error
    rather than a user-facing validation state.
    """
    for question in survey.questions:
        if question.qid == question_id:
            return question
    raise SurveyToolError(
        ErrorCode.INTERNAL,
        "Something went wrong preparing this cross-tab.",
        detail=(
            f"Unknown question {question_id!r} in survey {survey.id!r}; "
            f"it is not among the survey's questions."
        ),
        next_action="Reload the file and try again.",
    )


def _nets_for_cell(qs_result, question: Question) -> dict[str, NetResult]:
    """Map the already-computed t2b/b2b figures into the payload net shape.

    The percentage is QuestionStats' own value, used verbatim. The count is
    aggregated from the per-code counts compute_question_stats produced; it is
    never derived from the percentage, and no netting rule is re-expressed
    here beyond "which role's codes belong to which net".
    """
    nets: dict[str, NetResult] = {}
    for net_id, _label, role in _NET_DEFINITIONS:
        percentage = getattr(qs_result, net_id)
        if percentage is None:
            # Mirrors has_top/has_bottom gating: no codes in this role.
            continue
        count = sum(cs.n for cs in qs_result.code_stats if cs.role is role)
        nets[net_id] = NetResult(
            count=count, percentage=percentage, base_valid=qs_result.base
        )
    return nets


def _column_for_cell(
    cell: Cell,
    question: Question,
    q_responses: list[Response],
    config: ToolConfig,
) -> ColumnResult:
    # 1. Slice to this cell's respondents -- the exact pattern compute_cross_tab
    #    uses for a demographic subgroup, with an N-dimensional cell's id set
    #    standing in for the subgroup's.
    cell_responses = [r for r in q_responses if r.respondent_id in cell.respondent_ids]

    # 2. The existing netting/percentaging logic, called unmodified.
    qs_result = compute_question_stats(question, cell_responses)

    # 3. INV-6. base_valid is QuestionStats.base, built over
    #    _BASE_STATES = {answered, nonsubstantive}; everything else in the cell
    #    (not_asked / item_missing / no response row at all) is n_invalid.
    #    n_invalid is defined as the difference, so `base_valid + n_invalid ==
    #    base_cell` holds structurally by construction and can never fail --
    #    it is `a + (b - a) == b` for any integers. The real invariant worth
    #    guarding is `0 <= base_valid <= base_cell`: qs_result.base counts
    #    response ROWS for this qid (from compute_question_stats) while
    #    base_cell counts distinct respondent IDS (from cohort.Cell); if a
    #    data-quality issue ever produced duplicate response rows for one
    #    respondent+qid, base_valid could exceed base_cell and n_invalid would
    #    go negative, silently flowing into the payload. This assertion is a
    #    real runtime guard against that, per the build plan's "this identity
    #    is a test, not a comment".
    base_cell = cell.base_cell
    base_valid = qs_result.base
    n_invalid = base_cell - base_valid
    assert 0 <= base_valid <= base_cell, (
        f"INV-6 violated for cell {cell.key!r} on question {question.qid!r}: "
        f"base_valid={base_valid} out of range for base_cell={base_cell} "
        f"(n_invalid would be {n_invalid})"
    )

    # 4. Counts and percentages, both read straight off the CodeStats. pct is
    #    already computed over base_valid by frequency.py and is never
    #    recomputed here.
    counts = {str(cs.code): cs.n for cs in qs_result.code_stats}
    percentages = {str(cs.code): cs.pct for cs in qs_result.code_stats}

    # 5. Nets.
    nets = _nets_for_cell(qs_result, question)

    # 6. Band the cell.
    band = classify_band(base_cell, config)

    # 7. Suppression as post-processing: everything above has already run,
    #    including the INV-6 assertion, so identity checks still happen for
    #    suppressed cells. base_cell and band stay populated.
    if band is Band.suppressed:
        return ColumnResult(
            key=[[dimension, category] for dimension, category in cell.key],
            label_path=list(cell.label_path),
            base_cell=base_cell,
            base_valid=None,
            n_invalid=None,
            base_provenance=None,
            band=band,
            counts=None,
            percentages=None,
            nets=None,
        )

    base_provenance = (
        BaseProvenancePayload(
            routed=qs_result.provenance.routed,
            item_missing=qs_result.provenance.item_missing,
            nonsubstantive_excluded=qs_result.provenance.nonsubstantive_excluded,
        )
        if qs_result.provenance is not None
        else None
    )

    return ColumnResult(
        key=[[dimension, category] for dimension, category in cell.key],
        label_path=list(cell.label_path),
        base_cell=base_cell,
        base_valid=base_valid,
        n_invalid=n_invalid,
        base_provenance=base_provenance,
        band=band,
        counts=counts,
        percentages=percentages,
        nets=nets,
    )


def compute_breaks_crosstab(
    respondent_frame: pd.DataFrame,
    survey: Survey,
    break_spec: list[str],
    filter_spec: dict[str, list[str]],
    question_ids: list[str],
    registry: ResolvedRegistry,
    vendor: str,
    config: ToolConfig,
    display_orders: dict[str, list[str]] | None = None,
) -> list[QuestionResult]:
    """Compute an N-dimensional cross-tab for each requested question.

    Cells are resolved ONCE and reused across every requested question — the
    cohort a cell describes does not depend on which question is being
    computed, so re-resolving per question would be both wasteful and a route
    to inconsistency between questions in one payload.

    Expects an already-validated request: validation (break/filter spec
    legality) belongs to ``surveytool.core.break_filter.validate_request`` and
    is surfaced by ``surveytool.core.projection.project``, not repeated here.

    ``display_orders`` (Round C3): an optional qid -> manual label order map,
    pre-loaded by the caller from ``ProjectDisplayOrders``. Affects only
    ``QuestionResult.scale_points``' ordering and ``display_order_is_manual``
    -- every count/percentage/net/mean in ``columns`` comes from
    ``compute_question_stats`` exactly as before and is completely
    unaffected by display order.
    """
    filtered_ids = apply_filter(respondent_frame, filter_spec, registry, survey, vendor)
    cells = resolve_cells(
        respondent_frame, filtered_ids, break_spec, registry, survey, vendor
    )

    base_total = len(respondent_frame)
    base_filtered = len(filtered_ids)

    # Task 9: any declared-not-collected category on a dimension actually
    # broken out here gets a plain-English note attached to the result, so a
    # table/chart never silently omits a canonical category without saying
    # why. Filtered to break_spec so a result never carries a note about a
    # dimension it doesn't display.
    break_dims = set(break_spec)
    demographic_notices = [
        f"{entry.dimension_label} — '{entry.category_label}' was not collected by this vendor: {entry.reason}"
        for entry in registry.not_collected_for_vendor(vendor)
        if entry.dimension in break_dims
    ]

    # Index responses by qid once, rather than re-scanning survey.responses per
    # question per cell -- the same pattern compute_survey_stats uses.
    response_index: dict[str, list[Response]] = {}
    for response in survey.responses:
        response_index.setdefault(response.qid, []).append(response)

    results: list[QuestionResult] = []
    for question_id in question_ids:
        question = _resolve_question(survey, question_id)
        q_responses = response_index.get(question.qid, [])

        columns = [
            _column_for_cell(cell, question, q_responses, config) for cell in cells
        ]

        manual_label_order = display_orders.get(question.qid) if display_orders else None

        results.append(
            QuestionResult(
                question_id=question.qid,
                question_text=question.text,
                scale_id=question.scale_family,
                scale_variant=question.scale_variant,
                scale_points=_scale_points(question, manual_label_order),
                nets=_net_definitions(question),
                base_total=base_total,
                base_filtered=base_filtered,
                columns=columns,
                demographic_notices=demographic_notices,
                display_order_is_manual=bool(display_orders and question.qid in display_orders),
            )
        )

    return results

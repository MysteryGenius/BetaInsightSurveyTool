"""The default (no manual reorder) display order of a question's answer
labels, for charts and the list beneath them (v4 feedback F3).

Never the order codes happen to have: Milieu and Toluna assign codes by
first appearance in the data, which carries no meaning.

- Scale questions: scales.yaml rank, positive end first (rank N .. 1), then
  any unranked labels (e.g. "Don't know") in their original order.
- Answers that feed a demographic dimension: the canonical registry's
  category order (canonical.yaml), then any label the vendor mapping can't
  place, in original order.
- Anything else: original order.

A saved manual order (Round C3) still overrides all of this.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from surveytool.core.cohort import _code_to_label_for_column, _resolve_raw_to_canonical
from surveytool.core.demographic_registry import ResolvedRegistry
from surveytool.core.model import Question, Survey


def _scale_order(question: Question) -> list[str] | None:
    ranked = [sc for sc in question.labels if sc.rank is not None]
    if not ranked:
        return None
    ranked.sort(key=lambda sc: sc.rank, reverse=True)
    unranked = [sc for sc in question.labels if sc.rank is None]
    return [sc.label for sc in ranked + unranked]


def _registry_order(
    question: Question, survey: Survey, registry: ResolvedRegistry, vendor: str
) -> list[str] | None:
    for dimension_name, mapping in registry.dimensions_for_vendor(vendor).items():
        if mapping.source_column != question.qid:
            continue
        canonical = registry.canonical.dimensions.get(dimension_name)
        if canonical is None or canonical.multi_select:
            return None
        category_order = {c.value: c.order for c in canonical.categories}
        code_to_label = _code_to_label_for_column(survey, question.qid)
        n = len(question.labels)

        def key(indexed):
            i, sc = indexed
            value = _resolve_raw_to_canonical(str(sc.code), mapping.value_map, code_to_label)
            return (category_order.get(value, n + 1) if value is not None else n + 1, i)

        return [sc.label for _, sc in sorted(enumerate(question.labels), key=key)]
    return None


def natural_label_order(
    question: Question,
    survey: Survey | None = None,
    registry: ResolvedRegistry | None = None,
    vendor: str | None = None,
) -> list[str]:
    order = _scale_order(question)
    if order is None and survey is not None and registry is not None and vendor is not None:
        order = _registry_order(question, survey, registry, vendor)
    return order if order is not None else [sc.label for sc in question.labels]


@dataclass
class ChartOrders:
    """Natural label orders for one survey: by question id, and by legacy
    banner breakdown variable ("age", "ethnicity") for the xbreak charts'
    group order."""

    by_qid: dict[str, list[str]] = field(default_factory=dict)
    by_breakdown: dict[str, list[str]] = field(default_factory=dict)


def chart_orders(
    survey: Survey,
    registry: ResolvedRegistry | None = None,
    vendor: str | None = None,
    banner: list[str] | None = None,
) -> ChartOrders:
    from surveytool.findings.sheet import _DEFAULT_BANNER, _find_banner_question

    orders = ChartOrders(
        by_qid={q.qid: natural_label_order(q, survey, registry, vendor) for q in survey.questions}
    )
    for name in banner if banner is not None else _DEFAULT_BANNER:
        banner_question = _find_banner_question(survey, name)
        if banner_question is not None:
            orders.by_breakdown[name] = orders.by_qid[banner_question.qid]
    return orders

from __future__ import annotations

import csv
import logging
import re
import tempfile
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import openpyxl
import pandas as pd
import yaml
from fastapi import FastAPI, Request, UploadFile, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from surveytool.charts.chart_data import build_chart_data, render_charts_plotly
from surveytool.charts.errors import (
    ErrorCode,
    NoSessionError,
    RenameFailedError,
    SurveyIdAlreadyExistsError,
    SurveyToolError,
    UnresolvedQuestionsError,
    WarningCode,
)
from surveytool.charts.plotly_renderer import build_figure, build_legacy_figure, rasterize
from surveytool.charts.styles import get_style
from surveytool.compute.breaks_compute import QuestionResult, compute_breaks_crosstab
from surveytool.compute.cross_tab import compute_cross_tab, detect_available_demographics
from surveytool.core.break_filter import validate_request
from surveytool.core.breaks_models import (
    BreakSpec,
    BreaksFigureRequest,
    BulkExportRequest,
    CrosstabRequest,
    ExportRequest,
    FilterSpec,
    ProjectionRequest,
    RegistryCategory,
    RegistryDimension,
    RegistryPayload,
)
from surveytool.core.breaks_payload import attach_chart_permissions
from surveytool.core.config import ToolConfig, load_config
from surveytool.core.demographic_registry import ResolvedRegistry, load_registry
from surveytool.core.model import CodeRole, QuestionType, Survey
from surveytool.core.projection import Projection, project
from surveytool.core.respondent_frame import to_respondent_frame
from surveytool.core.straightliner import detect_straightliners
from surveytool.findings.sheet import build_findings_sheet
from surveytool.ingest.column_inventory import build_column_classifications
from surveytool.ingest.fingerprint import check_fingerprint
from surveytool.ingest.chart_style import (
    ChartStyleChoice,
    delete_chart_style,
    load_chart_styles,
    write_chart_style,
)
from surveytool.ingest.display_order import (
    DisplayOrder,
    delete_display_order,
    load_display_orders,
    write_display_order,
)
from surveytool.ingest.overrides import (
    OverrideNotice,
    QuestionOverride,
    apply_override,
    check_override_still_needed,
    load_overrides,
    write_override,
)
from surveytool.ingest.run_summary import RunSummary, build_run_summary
from surveytool.ingest.validate_questions import assert_no_duplicate_codes
from surveytool.ingest.vendor_profile import get_vendor_profile

_STATIC_DIR = Path(__file__).parent / "static"
_DEMOGRAPHICS_DIR = Path(__file__).parent.parent / "core" / "demographics"
_STORAGE_DIR = Path(tempfile.gettempdir()) / "surveytool-sessions"
# Overrides are the analyst's resolved work product for a project and must
# survive a reboot, unlike uploaded-file staging (_STORAGE_DIR) which is
# disposable. Path.home() is the same persistence root the desktop shell
# already treats as durable (surveytool/desktop/main.py's _default_export_dir
# falls back to it), so project data lives under it rather than in a
# location an OS is free to sweep (tempfile.gettempdir()).
_APP_DATA_DIR = Path.home() / ".surveytool"
_OVERRIDES_DIR = _APP_DATA_DIR / "overrides"
_OLD_OVERRIDES_DIR = Path(tempfile.gettempdir()) / "surveytool-overrides"
_SETTINGS_DIR = Path(tempfile.gettempdir()) / "surveytool-settings"
_DISPLAY_ORDER_DIR = _APP_DATA_DIR / "display_order"
_CHART_STYLE_DIR = _APP_DATA_DIR / "chart_style"
_logger = logging.getLogger(__name__)

app = FastAPI()

_VENDORS = ("rakuten", "milieu", "toluna", "purespectrum")
_VENDOR_LABELS = {
    "rakuten": "Rakuten",
    "milieu": "Milieu",
    "toluna": "Toluna",
    "purespectrum": "PureSpectrum",
}

_SCALE_LIBRARY_VERSION = "1.0.0"

_CANONICAL_PATH = _DEMOGRAPHICS_DIR / "canonical.yaml"
_VENDOR_REGISTRY_PATHS = {
    vendor: _DEMOGRAPHICS_DIR / f"vendor_{vendor}.yaml" for vendor in _VENDORS
}


@app.exception_handler(SurveyToolError)
async def _survey_tool_error_handler(request: Request, exc: SurveyToolError) -> JSONResponse:
    if exc.code is ErrorCode.INTERNAL:
        _logger.exception("Internal error handling %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=exc.status_code, content=exc.to_response())


@app.exception_handler(Exception)
async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    _logger.exception("Unhandled error handling %s %s", request.method, request.url.path, exc_info=exc)
    fallback = SurveyToolError(
        ErrorCode.INTERNAL,
        "Something failed while processing your request. Check the app log for details.",
    )
    return JSONResponse(status_code=fallback.status_code, content=fallback.to_response())


@dataclass
class Session:
    survey: Survey
    respondent_frame: pd.DataFrame
    findings: list
    vendor: str
    registry: ResolvedRegistry
    survey_id: str
    file_path: Path
    run_summary: RunSummary


@dataclass
class PendingSession:
    """Round A prompt A8: a session for a file that raised
    UnresolvedQuestionsError on its first load attempt — before this, such
    a file produced no session at all (the exception propagated out of
    _run_pipeline before Session construction), so the resolver panel had
    a session_id to show but no session to resolve against, and
    /resolve's session_id ended up either null or a stale one from a
    previous upload.

    Carries only what /resolve actually needs to write overrides and
    re-run the load: vendor/file_path/survey_id. Deliberately NOT a full
    Session — no survey, respondent_frame, findings, registry, or
    run_summary exist yet, since load() never returned one. Every other
    endpoint keeps requiring a full Session via _require_session; only the
    resolve endpoint accepts either shape (see _require_resolvable_session).
    """

    vendor: str
    survey_id: str
    file_path: Path


def _project_settings_path(survey_id: str) -> Path:
    """Per-survey_id project settings (prompt 9: non-substantive response
    handling). Mirrors _project_overrides_path's validation and layout —
    one small YAML file per survey_id, in its own directory alongside the
    overrides store."""
    _validate_survey_id(survey_id)
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    candidate = (_SETTINGS_DIR / f"{survey_id}.yaml").resolve()
    if _SETTINGS_DIR.resolve() not in candidate.parents:
        raise SurveyToolError(
            ErrorCode.CONFIG_INVALID,
            "Survey ID is not valid.",
            next_action="Use a shorter ID with only letters, numbers, '-', or '_'.",
        )
    return candidate


def _load_project_settings(survey_id: str) -> ToolConfig:
    path = _project_settings_path(survey_id)
    if not path.exists():
        return ToolConfig()
    return load_config(path)


def _save_project_settings(survey_id: str, settings: ToolConfig) -> None:
    path = _project_settings_path(survey_id)
    path.write_text(yaml.dump(settings.model_dump(mode="json")), encoding="utf-8")


def _default_config() -> ToolConfig:
    """Config for the breaks endpoints.

    The pre-existing endpoints let compute_cross_tab default its own config,
    so no session-level config is loaded at upload time. The breaks core
    functions take config as a required parameter, so this supplies the same
    defaults explicitly. A per-project config loader is a later concern.
    """
    return ToolConfig()


def _load_session_registry(vendor: str, survey: Survey) -> ResolvedRegistry:
    """Load and validate the demographic registry for an uploaded file.

    `surveys={vendor: survey}` runs the unmapped-source-value check (rule 2)
    against the file just loaded, so a source value this vendor's mapping
    doesn't cover fails the upload rather than silently disappearing from a
    later break. Any failure raises a SurveyToolError, which the app-level
    handler turns into a proper error response — the upload hard-fails and
    no partially-usable session is created.
    """
    return load_registry(_CANONICAL_PATH, _VENDOR_REGISTRY_PATHS, surveys={vendor: survey})


_SESSIONS: dict[str, Session] = {}
_PENDING_SESSIONS: dict[str, PendingSession] = {}


def get_session(session_id: str) -> Session | None:
    return _SESSIONS.get(session_id)


_SURVEY_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _validate_survey_id(survey_id: str) -> None:
    """survey_id is free-text the analyst types into the upload form and is
    interpolated directly into a filesystem path (_project_overrides_path).
    Without this check a value like '../../etc/cron.d/x' could write outside
    _OVERRIDES_DIR — reject anything but a conservative safe charset before
    it ever reaches a path."""
    if not _SURVEY_ID_RE.match(survey_id):
        raise SurveyToolError(
            ErrorCode.CONFIG_INVALID,
            "Survey ID can only contain letters, numbers, hyphens, and underscores.",
            detail=f"Rejected survey_id: {survey_id!r}.",
            next_action="Use a shorter ID with only letters, numbers, '-', or '_'.",
        )


def _resolve_under(base_dir: Path, survey_id: str) -> Path:
    """Build `base_dir/{survey_id}.yaml` and confirm the resolved path is
    actually contained in `base_dir`. `_validate_survey_id`'s allowlist regex
    already blocks the traversal characters this catches, but re-deriving
    the containment check against whichever base_dir is passed keeps the
    belt-and-suspenders property the audit called for, independent of which
    directory overrides happen to live in today."""
    base_dir.mkdir(parents=True, exist_ok=True)
    candidate = (base_dir / f"{survey_id}.yaml").resolve()
    if base_dir.resolve() not in candidate.parents:
        raise SurveyToolError(
            ErrorCode.CONFIG_INVALID,
            "Survey ID is not valid.",
            next_action="Use a shorter ID with only letters, numbers, '-', or '_'.",
        )
    return candidate


_MIGRATION_NOTICES: dict[str, str] = {}


def _migrate_legacy_override(survey_id: str, new_path: Path) -> None:
    """One-time migration read: if survey_id has an override file at the old
    tempdir location and none yet at the new persistent location, copy it
    forward and record a notice for the next run summary. The old file is
    left in place (not deleted) — this is a read, not a move, so a rollback
    or a second process racing this one can't lose data. A no-op once the
    new file exists, so this is safe to call on every path lookup."""
    if new_path.exists():
        return
    old_path = _resolve_under(_OLD_OVERRIDES_DIR, survey_id)
    if not old_path.exists():
        return
    new_path.write_text(old_path.read_text(encoding="utf-8"), encoding="utf-8")
    _MIGRATION_NOTICES[survey_id] = (
        f"Project overrides for '{survey_id}' were migrated from the old temporary "
        "storage location to persistent storage. Nothing was lost."
    )


def _last_migration_notice(survey_id: str) -> str | None:
    """Consumes (pops) the migration notice recorded for survey_id, if any,
    so it surfaces in the run summary exactly once — on the run whose
    _load_survey call actually triggered the migration."""
    return _MIGRATION_NOTICES.pop(survey_id, None)


def _project_overrides_path(survey_id: str) -> Path:
    """Overrides are scoped per survey_id — the only project-like identifier
    the analyst already provides at upload time. One YAML file per survey_id,
    shared across re-uploads of the same survey_id so a resolved question
    stays resolved on a later re-run of the same project.

    Stored under _APP_DATA_DIR (Path.home()/.surveytool), not the OS temp
    directory: the analyst's resolved work must survive a reboot, and temp
    directories are not guaranteed to (this is what moved the store off
    _OLD_OVERRIDES_DIR). Migrates forward from the old location transparently
    on first access after the move — see _migrate_legacy_override."""
    _validate_survey_id(survey_id)
    new_path = _resolve_under(_OVERRIDES_DIR, survey_id)
    _migrate_legacy_override(survey_id, new_path)
    return new_path


def _project_display_order_path(survey_id: str) -> Path:
    """Per-survey_id manual display-order store (Round C3). Mirrors
    _project_overrides_path's validation/layout — one YAML file per
    survey_id, in its own directory. No legacy-migration concern here
    since this is a brand-new file kind with no prior tempdir location,
    unlike overrides' _migrate_legacy_override — this file has always
    lived under _APP_DATA_DIR from its first day."""
    _validate_survey_id(survey_id)
    new_path = _resolve_under(_DISPLAY_ORDER_DIR, survey_id)
    return new_path


def _load_display_orders_for_survey(survey_id: str) -> dict[str, list[str]]:
    path = _project_display_order_path(survey_id)
    orders = load_display_orders(path)
    return {qid: entry.label_order for qid, entry in orders.orders.items()}


def _project_chart_style_path(survey_id: str) -> Path:
    """Per-survey_id chart-style store. Mirrors _project_display_order_path's
    validation/layout exactly -- one YAML file per survey_id, in its own
    directory. No legacy-migration concern, same as display_order.py: this
    is a brand-new file kind with no prior tempdir location."""
    _validate_survey_id(survey_id)
    return _resolve_under(_CHART_STYLE_DIR, survey_id)


def _load_chart_styles_for_survey(survey_id: str) -> dict[str, str]:
    path = _project_chart_style_path(survey_id)
    styles = load_chart_styles(path)
    return {qid: entry.style_name for qid, entry in styles.styles.items()}


def _load_response_colours_for_survey(survey_id: str) -> dict[str, dict[str, str]]:
    path = _project_chart_style_path(survey_id)
    styles = load_chart_styles(path)
    return {
        qid: entry.response_colours
        for qid, entry in styles.styles.items()
        if entry.response_colours
    }


def _read_fingerprint_signals(path: Path) -> tuple[frozenset[str], frozenset[str]]:
    """Read just enough of an uploaded file to run the fingerprint pre-check:
    its sheet names (xlsx only) and the union of every sheet's header row
    (xlsx) or the CSV header row (Milieu). Not a full parse — read_only mode,
    header rows only. Returns empty sets if the file can't be opened at all,
    which check_fingerprint's vacuous-match guard treats as "no signature
    data available" rather than a match.
    """
    if path.suffix.lower() == ".xlsx":
        try:
            wb = openpyxl.load_workbook(path, read_only=True)
        except (InvalidFileException, OSError, KeyError, zipfile.BadZipFile):
            return frozenset(), frozenset()
        try:
            sheet_names = frozenset(wb.sheetnames)
            column_names: set[str] = set()
            for sheetname in wb.sheetnames:
                ws = wb[sheetname]
                header = next(ws.iter_rows(max_row=1, values_only=True), None)
                if header:
                    column_names.update(str(cell) for cell in header if cell is not None)
        finally:
            wb.close()
        return sheet_names, frozenset(column_names)

    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            header = next(csv.reader(f), None)
    except (OSError, UnicodeDecodeError, csv.Error):
        return frozenset(), frozenset()
    if header is None:
        return frozenset(), frozenset()
    return frozenset(), frozenset(cell.strip() for cell in header)


def _load_survey(path: Path, survey_id: str, vendor: str, settings: ToolConfig | None = None) -> Survey:
    """`settings`, when provided, supplies the project's configured
    non-substantive label list (Task 7) to the vendor adapter's load().
    None falls back to the adapter's own built-in defaults — callers that
    haven't loaded project settings yet get identical behavior to before
    this was configurable."""
    if vendor == "rakuten":
        from surveytool.ingest.rakuten import load
    elif vendor == "milieu":
        from surveytool.ingest.milieu import load
    elif vendor == "toluna":
        from surveytool.ingest.toluna import load
    elif vendor == "purespectrum":
        from surveytool.ingest.purespectrum import load
    else:
        raise SurveyToolError(
            ErrorCode.VENDOR_MISMATCH,
            "This vendor is not recognised.",
            detail=f"Unknown vendor {vendor!r}.",
            next_action=f"Choose one of: {', '.join(_VENDORS)}.",
        )

    sheet_names, column_names = _read_fingerprint_signals(path)
    check_fingerprint(vendor, sheet_names=sheet_names, column_names=column_names)

    overrides = load_overrides(_project_overrides_path(survey_id)).overrides
    nonsubstantive_labels = settings.nonsubstantive_labels if settings is not None else None
    return load(path, survey_id, overrides, nonsubstantive_labels)


def _require_session(session_id: str) -> Session:
    session = get_session(session_id)
    if session is None:
        raise NoSessionError()
    return session


def _require_resolvable_session(session_id: str) -> Session | PendingSession:
    """Round A prompt A8: the resolve endpoint's session lookup, tolerant
    of a PendingSession (a file that raised UnresolvedQuestionsError on
    its first load and so never produced a full Session) in addition to a
    normal completed Session. Every other endpoint keeps using
    _require_session, which only ever recognises a full Session."""
    session = get_session(session_id)
    if session is not None:
        return session
    pending = _PENDING_SESSIONS.get(session_id)
    if pending is not None:
        return pending
    raise NoSessionError()


def _column_qid_map(
    vendor: str, path: Path, survey_id: str, settings: ToolConfig | None = None
) -> tuple[list[str], dict[str, str]]:
    """Toluna's column_qid_map re-derives qids via its own internal
    parse_header call — without the same project overrides _load_survey
    used, a question that only classifies successfully because of an
    override (e.g. its raw labels would otherwise raise
    UnresolvedScaleLabelsError) would make this second, override-blind
    parse fail even though the real load() already succeeded. Passing the
    same overrides here keeps both parses consistent. The same reasoning
    applies to the project's configured non-substantive label list (Task
    7): a custom list can change which labels are substantive and thus
    change match_family's outcome, so `settings` is threaded through here
    too. The other three vendors' column_qid_map don't take overrides —
    their qid derivation doesn't depend on classification, so this is a
    no-op for them.
    """
    if vendor == "rakuten":
        from surveytool.ingest.rakuten import column_qid_map
        return column_qid_map(path)
    if vendor == "milieu":
        from surveytool.ingest.milieu import column_qid_map
        return column_qid_map(path)
    if vendor == "toluna":
        from surveytool.ingest.toluna import column_qid_map
        overrides = load_overrides(_project_overrides_path(survey_id)).overrides
        nonsubstantive_labels = settings.nonsubstantive_labels if settings is not None else None
        return column_qid_map(path, overrides, nonsubstantive_labels)
    if vendor == "purespectrum":
        from surveytool.ingest.purespectrum import column_qid_map
        return column_qid_map(path)
    return [], {}


def _read_status_values(vendor: str, path: Path) -> list[str]:
    """Only PureSpectrum and Milieu's real fixtures carry a 'status'
    column; Rakuten and Toluna have none, so disposition_counts is
    legitimately empty for those vendors rather than an extraction bug."""
    if vendor == "purespectrum":
        from surveytool.ingest.purespectrum import read_status_values
    elif vendor == "milieu":
        from surveytool.ingest.milieu import read_status_values
    else:
        return []
    return read_status_values(path)


def _verification_sheet_used(vendor: str, path: Path) -> bool:
    profile = get_vendor_profile(vendor)
    if profile.verification_sheet is None or path.suffix.lower() != ".xlsx":
        return False
    try:
        wb = openpyxl.load_workbook(path, read_only=True)
    except (InvalidFileException, OSError, KeyError, zipfile.BadZipFile):
        return False
    try:
        return profile.verification_sheet in wb.sheetnames
    finally:
        wb.close()


_MEAN_NEWLY_AVAILABLE_VENDORS = frozenset({"toluna", "milieu"})


def _mean_newly_available_entries(vendor: str, survey: Survey, findings: list) -> list[dict]:
    """Round B4: Toluna and Milieu never had a numeric vendor code to derive
    a mean from before Round B introduced rank (both vendors' scale
    questions are text-labelled, with no real numeric code of their own --
    see toluna.py/milieu.py's _build_scale_question docstrings). Now that
    rank drives mean for every vendor uniformly, a scale question's mean is
    newly available for these two vendors specifically -- Rakuten and
    PureSpectrum already had a vendor numeric code and so already had *a*
    mean before this round (Round B only corrected which order it uses, see
    test_purespectrum_inverted_questions_mean_now_derives_from_rank_not_code),
    so the flag never fires for them. Surfaced in the run summary so an
    analyst comparing this run to a pre-Round-B one understands why a new
    figure appeared, rather than wondering if it's a bug.
    """
    if vendor not in _MEAN_NEWLY_AVAILABLE_VENDORS:
        return []

    scale_qids = {
        q.qid for q in survey.questions
        if q.qtype is QuestionType.scale
    }
    if not scale_qids:
        return []

    mean_by_qid: dict[str, float] = {}
    for row in findings:
        if (
            row.breakdown_variable == "total"
            and row.metric == "mean"
            and row.qid in scale_qids
            and row.value is not None
        ):
            mean_by_qid[row.qid] = row.value

    questions_by_qid = {q.qid: q for q in survey.questions}
    entries = []
    for qid in sorted(mean_by_qid):
        question = questions_by_qid[qid]
        entries.append({
            "variable": qid,
            "message": (
                f"'{qid}' now has a mean ({mean_by_qid[qid]:.2f}). {vendor.title()} "
                "supplies no vendor numeric code for scale questions, so no mean was "
                "computable before Round B's rank-based mean -- this figure is newly "
                "available in this run."
            ),
        })
    return entries


def _build_session_run_summary(
    vendor: str,
    path: Path,
    survey: Survey,
    survey_id: str,
    registry: ResolvedRegistry,
    straightliner_count: int = 0,
    straightliner_action: str = "keep",
    settings: ToolConfig | None = None,
    findings: list | None = None,
) -> RunSummary:
    profile = get_vendor_profile(vendor)
    header, qid_by_column = _column_qid_map(vendor, path, survey_id, settings)
    column_classifications = build_column_classifications(header, qid_by_column, survey, profile)
    status_values = _read_status_values(vendor, path)
    verification_sheet_used = _verification_sheet_used(vendor, path)

    project_overrides = load_overrides(_project_overrides_path(survey_id)).overrides
    questions_by_qid = {q.qid: q for q in survey.questions}
    overrides_applied = [
        (variable, override.resolved_at)
        for variable, override in project_overrides.items()
        if variable in questions_by_qid
    ]
    override_notices = []
    migration_notice = _last_migration_notice(survey_id)
    if migration_notice is not None:
        override_notices.append(OverrideNotice(variable=survey_id, message=migration_notice))
    for variable, override in project_overrides.items():
        question = questions_by_qid.get(variable)
        if question is None:
            continue
        substantive_labels = [sc.label for sc in question.labels if sc.role != CodeRole.nonsubstantive]
        notice = check_override_still_needed(variable, substantive_labels, override)
        if notice is not None:
            override_notices.append(notice)

    categorical_classifications = [
        (q.qid, q.categorical_reason)
        for q in survey.questions
        if q.qtype is QuestionType.categorical and q.categorical_reason is not None
    ]

    mean_newly_available = _mean_newly_available_entries(vendor, survey, findings or [])

    return build_run_summary(
        profile=profile,
        column_classifications=column_classifications,
        status_values=status_values,
        override_notices=override_notices,
        overrides_applied=overrides_applied,
        verification_sheet_used=verification_sheet_used,
        straightliner_count=straightliner_count,
        straightliner_action=straightliner_action,
        not_collected=registry.not_collected_for_vendor(vendor),
        categorical_classifications=categorical_classifications,
        mean_newly_available=mean_newly_available,
    )


def _run_pipeline(file_path: Path, survey_id: str, vendor: str) -> tuple[Session, list[dict]]:
    """Shared pipeline for both a fresh upload and a resolver-triggered
    re-run: load, register demographics, detect straightliners, build
    findings. Returns a Session (not yet stored under a session_id) and the
    warnings list the API response includes.
    """
    settings = _load_project_settings(survey_id)
    survey = _load_survey(file_path, survey_id, vendor, settings)
    registry = _load_session_registry(vendor, survey)
    flagged = detect_straightliners(survey.responses, survey.questions)
    excluded = flagged if settings.straightliner_action == "exclude" else set()
    display_order_manual_qids = set(_load_display_orders_for_survey(survey_id))
    findings = build_findings_sheet(
        survey,
        exclude_respondent_ids=excluded or None,
        exclude_nonsubstantive_from_base=settings.exclude_nonsubstantive_from_base,
        display_order_manual_qids=display_order_manual_qids,
    )
    respondent_frame = to_respondent_frame(survey)
    run_summary = _build_session_run_summary(
        vendor,
        file_path,
        survey,
        survey_id,
        registry,
        straightliner_count=len(flagged),
        straightliner_action=settings.straightliner_action,
        settings=settings,
        findings=findings,
    )

    session = Session(
        survey=survey,
        respondent_frame=respondent_frame,
        findings=findings,
        vendor=vendor,
        registry=registry,
        survey_id=survey_id,
        file_path=file_path,
        run_summary=run_summary,
    )

    warnings = []
    if excluded:
        warnings.append({
            "code": WarningCode.STRAIGHTLINERS_EXCLUDED.value,
            "message": f"{len(excluded)} respondent(s) were excluded for straightlining.",
        })
    return session, warnings


@app.post("/api/upload")
async def upload(file: UploadFile, vendor: str = Form(...), survey_id: str = Form(...)):
    session_id = str(uuid.uuid4())
    session_dir = _STORAGE_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    stored_path = session_dir / Path(file.filename).name
    stored_path.write_bytes(await file.read())

    try:
        session, warnings = _run_pipeline(stored_path, survey_id, vendor)
    except UnresolvedQuestionsError as exc:
        # Round A prompt A8: a file needing resolution still produces a
        # session — a PendingSession under this same session_id — so the
        # resolver panel the client shows for this error can actually
        # resolve and save against it. Before this, the exception
        # propagated out with no session ever created; the resolver
        # offered Confirm and Save with nowhere to save to.
        _PENDING_SESSIONS[session_id] = PendingSession(
            vendor=vendor, survey_id=survey_id, file_path=stored_path
        )
        body = exc.to_response()
        body["error"]["session_id"] = session_id
        body["error"]["survey_id"] = survey_id
        return JSONResponse(status_code=exc.status_code, content=body)

    _SESSIONS[session_id] = session

    return {
        "session_id": session_id,
        "survey_id": survey_id,
        "n_raw": session.survey.n_raw,
        "n_analysis": session.survey.n_analysis,
        "question_count": len(session.survey.questions),
        "warnings": warnings,
    }


class ResolvedQuestionPayload(BaseModel):
    """One resolver answer: the classification the analyst chose for a
    variable, plus the label->role assignment for the scale case (empty for
    binary/categorical/excluded, which need no per-label roles)."""

    variable: str
    question_type: Literal["scale", "binary", "categorical", "excluded"]
    label_roles: dict[str, Literal["top", "neutral", "bottom"]] = {}
    label_ranks: dict[str, int] | None = None


class ResolveRequest(BaseModel):
    resolutions: list[ResolvedQuestionPayload]


@app.post("/api/session/{session_id}/resolve")
async def resolve_questions(session_id: str, request: ResolveRequest):
    """Writes the resolver's whole answer set as project overrides, then
    re-runs the file load so the resolved questions take effect immediately.

    Writes only after every entry validates — apply_override's
    IncompleteOverrideError is not reachable here (the resolver enforces
    every label assigned before allowing save), but a scale entry missing a
    role due to a client bug must still fail the whole batch rather than
    write some overrides and skip others, so validation happens in one pass
    before any write.
    """
    session = _require_resolvable_session(session_id)
    overrides_path = _project_overrides_path(session.survey_id)
    now = datetime.now(timezone.utc)

    # A PendingSession (Round A prompt A8) has no .survey — its file never
    # produced one — so there is no existing Question to validate a scale
    # override's label set against; apply_override falls back to
    # entry.label_roles' own keys in that case (see below).
    if isinstance(session, Session):
        question_labels_by_variable = {
            q.qid: [sc.label for sc in q.labels if sc.role != CodeRole.nonsubstantive]
            for q in session.survey.questions
        }
        question_codes_by_variable = {
            q.qid: [(sc.code, sc.label) for sc in q.labels if sc.role != CodeRole.nonsubstantive]
            for q in session.survey.questions
        }
    else:
        question_labels_by_variable = {}
        question_codes_by_variable = {}

    validated: list[QuestionOverride] = []
    for entry in request.resolutions:
        override = QuestionOverride(
            variable=entry.variable,
            question_type=entry.question_type,
            label_roles=entry.label_roles,
            label_ranks=entry.label_ranks,
            resolved_at=now,
            library_version=_SCALE_LIBRARY_VERSION,
        )
        if override.question_type == "scale":
            labels = question_labels_by_variable.get(entry.variable, list(entry.label_roles.keys()))
            codes = question_codes_by_variable.get(entry.variable)
            if codes is not None:
                # Round A prompt A2: an override that would collapse two
                # codes onto one label must raise here, at write time,
                # before anything is persisted — not silently drop one
                # code's role assignment because dict keys can't duplicate.
                assert_no_duplicate_codes(entry.variable, codes)
            apply_override(labels, override)  # raises IncompleteOverrideError, caught by the app-level handler
        validated.append(override)

    for override in validated:
        write_override(overrides_path, override)

    try:
        new_session, warnings = _run_pipeline(session.file_path, session.survey_id, session.vendor)
    except UnresolvedQuestionsError as exc:
        # This save didn't cover every unresolved question (or the resolver
        # sent an incomplete batch) — the session stays resolvable under
        # this same session_id rather than vanishing, exactly as an
        # initial upload's UnresolvedQuestionsError now behaves (see
        # upload()).
        _PENDING_SESSIONS[session_id] = PendingSession(
            vendor=session.vendor, survey_id=session.survey_id, file_path=session.file_path
        )
        body = exc.to_response()
        body["error"]["session_id"] = session_id
        return JSONResponse(status_code=exc.status_code, content=body)

    _SESSIONS[session_id] = new_session
    _PENDING_SESSIONS.pop(session_id, None)

    return {
        "session_id": session_id,
        "n_raw": new_session.survey.n_raw,
        "n_analysis": new_session.survey.n_analysis,
        "question_count": len(new_session.survey.questions),
        "warnings": warnings,
    }


@app.post("/api/session/{session_id}/rerun")
async def rerun_session(session_id: str):
    """Re-runs the current session's file from scratch, picking up any
    project setting changed since the original upload (prompt 9: changing
    the non-substantive exclude toggle invalidates the current result and
    requires this). Distinct from /resolve, which re-runs as a side effect
    of writing overrides — this re-runs with no override changes, purely to
    pick up a settings change."""
    session = _require_session(session_id)
    new_session, warnings = _run_pipeline(session.file_path, session.survey_id, session.vendor)
    _SESSIONS[session_id] = new_session
    return {
        "session_id": session_id,
        "n_raw": new_session.survey.n_raw,
        "n_analysis": new_session.survey.n_analysis,
        "question_count": len(new_session.survey.questions),
        "warnings": warnings,
    }


class ProjectSettingsPayload(BaseModel):
    nonsubstantive_labels: list[str]
    exclude_nonsubstantive_from_base: bool
    straightliner_action: Literal["keep", "exclude"] = "keep"


@app.get("/api/projects/{survey_id}/settings")
async def get_project_settings(survey_id: str) -> ProjectSettingsPayload:
    """Project settings for non-substantive response handling (prompt 9)
    and straightliner disposition (Round A prompt A6, finding 2). Keyed by
    survey_id directly (not session_id) since these are project-level,
    editable before or independent of any active upload session."""
    settings = _load_project_settings(survey_id)
    return ProjectSettingsPayload(
        nonsubstantive_labels=settings.nonsubstantive_labels,
        exclude_nonsubstantive_from_base=settings.exclude_nonsubstantive_from_base,
        straightliner_action=settings.straightliner_action,
    )


@app.post("/api/projects/{survey_id}/settings")
async def update_project_settings(survey_id: str, payload: ProjectSettingsPayload) -> ProjectSettingsPayload:
    """Saves the settings. Does not itself re-run anything — any existing
    session for this survey_id is now stale (its findings were built under
    the old setting) and the caller is responsible for re-running, exactly
    as the resolver's own save-then-rerun flow works. The UI enforces this
    by requiring a re-run before showing results again once a setting
    changes underneath an open session.

    Round A prompt A6 (finding 2): straightliner_action was previously not
    exposed on this payload at all, so every save silently reset it to the
    ToolConfig class default ("keep") regardless of what had been saved
    before — this constructs the new config from the existing saved one
    (falling back to defaults only when nothing was saved yet) rather than
    a bare ToolConfig(), so a field this endpoint doesn't yet expose (or
    that an older client's request body omits) is preserved instead of
    being silently discarded on the next save. Only fields actually present
    in the request body (payload.model_fields_set) overwrite the existing
    value — an omitted field is left untouched, not reset to its schema
    default, which is the distinction plain attribute access can't make
    since pydantic already filled the default in by the time the handler
    sees `payload`.
    """
    existing = _load_project_settings(survey_id)
    updates = {
        field: getattr(payload, field)
        for field in ("nonsubstantive_labels", "exclude_nonsubstantive_from_base", "straightliner_action")
        if field in payload.model_fields_set
    }
    settings = existing.model_copy(update=updates)
    _save_project_settings(survey_id, settings)
    return ProjectSettingsPayload(
        nonsubstantive_labels=settings.nonsubstantive_labels,
        exclude_nonsubstantive_from_base=settings.exclude_nonsubstantive_from_base,
        straightliner_action=settings.straightliner_action,
    )


class DisplayOrderPayload(BaseModel):
    label_order: list[str]


@app.get("/api/projects/{survey_id}/display-order/{qid}")
async def get_display_order(survey_id: str, qid: str) -> DisplayOrderPayload | None:
    """Round C3: the analyst's saved manual display order for one question,
    if any. Keyed by survey_id directly (not session_id), same as project
    settings — editable independent of any active upload session. Returns
    None (204-shaped null body) when no manual order has been saved, so the
    UI can distinguish 'default rank order' from 'a saved order'."""
    path = _project_display_order_path(survey_id)
    orders = load_display_orders(path)
    entry = orders.orders.get(qid)
    if entry is None:
        return None
    return DisplayOrderPayload(label_order=entry.label_order)


@app.put("/api/projects/{survey_id}/display-order/{qid}")
async def put_display_order(survey_id: str, qid: str, payload: DisplayOrderPayload) -> DisplayOrderPayload:
    """Save a manual display order for one question. Does not itself
    recompute anything — the next crosstab call for this survey_id picks it
    up via _load_display_orders_for_survey (post_crosstab/post_breaks_export),
    exactly as a project-settings change is picked up on the next run."""
    path = _project_display_order_path(survey_id)
    order = DisplayOrder(
        variable=qid,
        label_order=payload.label_order,
        is_manual=True,
        saved_at=datetime.now(timezone.utc),
    )
    write_display_order(path, order)
    return payload


@app.delete("/api/projects/{survey_id}/display-order/{qid}")
async def reset_display_order(survey_id: str, qid: str) -> dict:
    """Reset one question back to its default order (rank order for scale
    questions, vendor-declared order for categorical) by deleting its saved
    manual order entirely. A no-op if no manual order was saved."""
    path = _project_display_order_path(survey_id)
    delete_display_order(path, qid)
    return {"reset": True}


class ChartStylePayload(BaseModel):
    style_name: str
    response_colours: dict[str, str] = Field(default_factory=dict)


@app.get("/api/projects/{survey_id}/chart-style/{qid}")
async def get_chart_style(survey_id: str, qid: str) -> ChartStylePayload | None:
    """The analyst's saved chart style for one question, if any. Keyed by
    survey_id directly (not session_id), same as display order -- editable
    independent of any active upload session. Returns None when no style
    has been saved, so the UI can distinguish 'default (brand) style' from
    'a saved style'."""
    path = _project_chart_style_path(survey_id)
    styles = load_chart_styles(path)
    entry = styles.styles.get(qid)
    if entry is None:
        return None
    return ChartStylePayload(style_name=entry.style_name, response_colours=entry.response_colours)


@app.put("/api/projects/{survey_id}/chart-style/{qid}")
async def put_chart_style(survey_id: str, qid: str, payload: ChartStylePayload) -> ChartStylePayload:
    """Save a chart style choice for one question. Does not itself
    recompute anything -- the next crosstab call for this survey_id picks
    it up via _load_chart_styles_for_survey (post_crosstab/
    post_breaks_export), exactly as a manual display order is picked up on
    the next run. write_chart_style raises UnknownChartStyleError (mapped
    to 400 by the app-level SurveyToolError handler) for a style_name not
    in STYLE_REGISTRY, and InvalidResponseColourError (same 400 mapping)
    for a response_colours value that isn't a well-formed hex colour."""
    path = _project_chart_style_path(survey_id)
    choice = ChartStyleChoice(
        variable=qid,
        style_name=payload.style_name,
        response_colours=payload.response_colours,
        saved_at=datetime.now(timezone.utc),
    )
    write_chart_style(path, choice)
    return payload


@app.delete("/api/projects/{survey_id}/chart-style/{qid}")
async def reset_chart_style(survey_id: str, qid: str) -> dict:
    """Reset one question back to the default (brand) style by deleting
    its saved choice entirely. A no-op if no style was saved."""
    path = _project_chart_style_path(survey_id)
    delete_chart_style(path, qid)
    return {"reset": True}


class RenamePayload(BaseModel):
    new_survey_id: str


@app.post("/api/projects/{survey_id}/rename")
async def rename_survey(survey_id: str, payload: RenamePayload):
    """Rename a survey_id, migrating every per-survey-keyed file
    (overrides, settings, display order, chart style) to the new key in one
    operation. Refuses onto an existing survey_id rather than merging. If
    migration cannot complete, every file already moved is moved back before
    raising, so the old survey_id is left fully intact.

    _PER_SURVEY_DIRS is built fresh on every call (not a module-level
    constant) so that test isolation which monkeypatches _OVERRIDES_DIR/
    _DISPLAY_ORDER_DIR onto the app module (see tests/conftest.py) is
    respected -- a constant captured once at import time would freeze in
    the real, non-isolated directories.
    """
    _validate_survey_id(survey_id)
    _validate_survey_id(payload.new_survey_id)  # raises 400 via the existing validator if malformed

    new_id = payload.new_survey_id
    per_survey_dirs: tuple[Path, ...] = (_OVERRIDES_DIR, _SETTINGS_DIR, _DISPLAY_ORDER_DIR, _CHART_STYLE_DIR)

    existing_new_paths = [d / f"{new_id}.yaml" for d in per_survey_dirs if (d / f"{new_id}.yaml").exists()]
    if existing_new_paths:
        raise SurveyIdAlreadyExistsError(new_id)

    moved: list[tuple[Path, Path]] = []
    try:
        for base_dir in per_survey_dirs:
            old_path = _resolve_under(base_dir, survey_id)
            if not old_path.exists():
                continue
            new_path = _resolve_under(base_dir, new_id)
            old_path.rename(new_path)
            moved.append((old_path, new_path))
    except OSError as exc:
        for old_path, new_path in reversed(moved):
            if new_path.exists():
                new_path.rename(old_path)
        raise RenameFailedError(survey_id, new_id, str(exc)) from exc

    return {"old_survey_id": survey_id, "new_survey_id": new_id, "files_migrated": len(moved)}


@app.get("/api/session/{session_id}/run-summary")
async def get_run_summary(session_id: str):
    """The run summary panel's data source (prompt 7/8): column inventory,
    classification counts, disposition counts, quality-flag and
    verification statements, override resolutions, and notices. Not opened
    automatically — the panel only fetches this when the analyst opens it
    from the result screen.
    """
    session = _require_session(session_id)
    summary = session.run_summary
    questions_by_qid = {q.qid: q for q in session.survey.questions}
    session_settings = _load_project_settings(session.survey_id)
    qid_by_column = _column_qid_map(session.vendor, session.file_path, session.survey_id, session_settings)[1]

    columns = []
    for column, classification in summary.column_classifications.items():
        qid = qid_by_column.get(column)
        question = questions_by_qid.get(qid) if qid is not None else None
        columns.append({
            "column": column,
            "question_text": question.text if question is not None else None,
            "classification": classification.value,
            "question_type": question.qtype.value if question is not None else None,
        })

    return {
        "columns": columns,
        "classification_counts": {k.value: v for k, v in summary.classification_counts.items()},
        "disposition_counts": summary.disposition_counts,
        "quality_flag_statement": summary.quality_flag_statement,
        "verification_statement": summary.verification_statement,
        "straightliner_statement": summary.straightliner_statement,
        "demographic_gap_statement": summary.demographic_gap_statement,
        "override_resolutions": summary.override_resolutions,
        "notices": summary.notices,
        "categorical_classifications": summary.categorical_classifications,
        "mean_newly_available": summary.mean_newly_available,
    }


@app.get("/api/session/{session_id}/charts")
async def get_charts(session_id: str):
    session = _require_session(session_id)
    display_orders = _load_display_orders_for_survey(session.survey_id)
    chart_styles = _load_chart_styles_for_survey(session.survey_id)
    response_colours = _load_response_colours_for_survey(session.survey_id)
    chart_data = build_chart_data(
        session.findings, session.survey.id, session.survey.questions,
        display_orders=display_orders,
    )

    # Item A (render parity): each chart carries the SERIALIZED Plotly figure
    # built by the very same build_legacy_figure call the PNG export path
    # (render_charts_plotly) makes for this chart, resolved from the same
    # style/colour overrides. charts.js renders this verbatim rather than
    # re-deriving its own trace/layout, so the on-screen chart and its
    # exported PNG are one figure and structurally cannot drift apart --
    # the guarantee the Cross-tab pipeline already had. The raw `trace`
    # field stays alongside it: the legend component still reads
    # `trace.labels` for its (unwrapped) response-option rows.
    charts = []
    for chart in chart_data:
        figure = build_legacy_figure(
            chart,
            get_style(chart_styles.get(chart.qid)),
            response_colours=response_colours.get(chart.qid),
        )
        entry = asdict(chart)
        entry["figure"] = figure.to_plotly_json()
        charts.append(entry)

    return {
        "charts": charts,
        "chart_styles": chart_styles,
        "response_colours": response_colours,
        "display_orders": display_orders,
    }


@app.post("/api/session/{session_id}/export")
async def export_charts(
    session_id: str,
    out_dir: str = Form(...),
    qid: str | None = Form(None),
    chart_type: str | None = Form(None),
    breakdown_variable: str | None = Form(None),
):
    session = _require_session(session_id)

    chart_filter = None
    if qid is not None or chart_type is not None or breakdown_variable is not None:
        chart_filter = (
            lambda spec: spec.qid == qid
            and spec.chart_type == chart_type
            and spec.breakdown_variable == breakdown_variable
        )

    try:
        entries = render_charts_plotly(
            session.findings,
            Path(out_dir),
            session.survey.id,
            session.survey.questions,
            display_orders=_load_display_orders_for_survey(session.survey_id),
            chart_styles=_load_chart_styles_for_survey(session.survey_id),
            response_colours=_load_response_colours_for_survey(session.survey_id),
            chart_filter=chart_filter,
        )
    except OSError as exc:
        raise SurveyToolError(
            ErrorCode.INTERNAL,
            "The export could not be saved to the chosen location.",
            detail=str(exc),
            next_action="Choose a different export location and try again.",
        ) from exc

    if chart_filter is not None and not entries:
        raise SurveyToolError(
            ErrorCode.INTERNAL,
            "This chart could not be found in the current session.",
            next_action="Reload the page and try exporting again.",
        )

    return {"exported": [e.filename for e in entries], "out_dir": out_dir}


@app.get("/api/session/{session_id}/demographics")
async def get_demographics(session_id: str):
    session = _require_session(session_id)

    availability = detect_available_demographics(session.survey)
    demographics = [
        {"key": key, "label": q.text}
        for key, q in {**availability.standard, **availability.conditional}.items()
    ]
    questions = [
        {"qid": q.qid, "text": q.text}
        for q in session.survey.questions
        if q.base_eligible and not q.is_demographic
    ]
    return {"demographics": demographics, "questions": questions}


@app.get("/api/session/{session_id}/cross-tab")
async def get_cross_tab(session_id: str, qid: str, demographic: str, significance: bool = False):
    session = _require_session(session_id)

    question = next((q for q in session.survey.questions if q.qid == qid), None)
    if question is None:
        # Not user-triggerable through the picker (which only ever sends qids
        # from /demographics) — this only fires on a malformed request.
        raise SurveyToolError(
            ErrorCode.INTERNAL,
            "This question could not be found in the current session.",
            detail=f"Unknown question {qid!r}.",
            next_action="Reload the page and choose a question from the list.",
        )

    try:
        result = compute_cross_tab(
            session.respondent_frame, session.survey, question, demographic,
            significance=significance,
        )
    except NotImplementedError as exc:
        # Significance stays inert until the restructure (build plan section 6,
        # item A) — the GUI never sends this parameter, so this path is not
        # reachable through normal use. No code in the minimum set fits "a
        # feature flag that isn't wired up yet," so this keeps its pre-existing
        # bare 400 response rather than being forced into the taxonomy.
        return JSONResponse(status_code=400, content={"error": str(exc)})

    return {
        "qid": result.qid,
        "question_text": result.question_text,
        "demographic": result.demographic,
        "cells": [
            {
                "subgroup_code": c.subgroup_code,
                "subgroup_label": c.subgroup_label,
                "n": c.n,
                "status": c.status.value,
                "t2b": c.t2b,
                "b2b": c.b2b,
                "mean": c.mean,
                "base_provenance": (
                    {
                        "routed": c.provenance.routed,
                        "item_missing": c.provenance.item_missing,
                        "nonsubstantive_excluded": c.provenance.nonsubstantive_excluded,
                    }
                    if c.provenance is not None
                    else None
                ),
            }
            for c in result.cells
        ],
    }


@app.get("/api/session/{session_id}/demographics/registry")
async def get_demographics_registry(session_id: str) -> RegistryPayload:
    """The canonical registry as resolved for this session's vendor.

    This is the UI's sole pill-list source (build plan section 12), so
    nothing is pruned: every canonical dimension is emitted with its full
    category list, including categories and dimensions this vendor does not
    map. `available` plus `source_column` record what this vendor actually
    declares, so the UI can disable rather than hide.

    Distinct from the pre-existing GET .../demographics, which serves the
    legacy single-break picker off detect_available_demographics and is
    unchanged.
    """
    session = _require_session(session_id)
    vendor_dims = session.registry.dimensions_for_vendor(session.vendor)

    dimensions = []
    for name, canonical_dim in session.registry.canonical.dimensions.items():
        dim_mapping = vendor_dims.get(name)
        not_collected = dim_mapping.not_collected if dim_mapping else {}
        dimensions.append(
            RegistryDimension(
                dimension=name,
                label=canonical_dim.label,
                multi_select=canonical_dim.multi_select,
                available=dim_mapping is not None,
                source_column=dim_mapping.source_column if dim_mapping else None,
                categories=[
                    RegistryCategory(
                        value=category.value,
                        label=category.label,
                        order=category.order,
                        non_response=category.non_response,
                        not_collected_reason=(
                            not_collected[category.value].reason
                            if category.value in not_collected
                            else None
                        ),
                    )
                    for category in canonical_dim.categories
                ],
            )
        )

    return RegistryPayload(vendor=session.vendor, dimensions=dimensions)


@app.post("/api/session/{session_id}/projection")
async def post_projection(session_id: str, request: ProjectionRequest) -> Projection:
    """The shape of a break/filter request, without computing any question.

    Returns 200 even for an invalid spec: project() reports validation
    failures in-band in Projection.errors rather than raising, because the
    UI re-runs this on every pill change and an in-progress selection is
    not an error condition (build plan section 6).
    """
    session = _require_session(session_id)
    return project(
        request.break_spec,
        request.filter_spec,
        session.survey,
        session.respondent_frame,
        session.registry,
        session.vendor,
        _default_config(),
    )


def _compute_breaks_results(
    session,
    break_spec: BreakSpec,
    filter_spec: FilterSpec,
    question_ids: list[str],
) -> list[QuestionResult]:
    """Validate -> compute -> attach chart permissions: the one path every
    Cross-tab route (crosstab, breaks-figure, both exports) goes through, so
    the figure on screen and the PNG exported are built from identical
    results with identical display-order/style/colour overrides."""
    config = _default_config()
    validate_request(
        break_spec,
        filter_spec,
        session.registry,
        session.survey,
        session.vendor,
        session.respondent_frame,
    )
    results = compute_breaks_crosstab(
        session.respondent_frame,
        session.survey,
        break_spec.dimensions,
        filter_spec.selections,
        question_ids,
        session.registry,
        session.vendor,
        config,
        display_orders=_load_display_orders_for_survey(session.survey_id),
        chart_styles=_load_chart_styles_for_survey(session.survey_id),
        response_colours=_load_response_colours_for_survey(session.survey_id),
    )
    return attach_chart_permissions(results, config)


@app.post("/api/session/{session_id}/crosstab")
async def post_crosstab(session_id: str, request: CrosstabRequest) -> list[QuestionResult]:
    """N-dimensional cross-tab for the requested questions.

    Validates first: compute_breaks_crosstab expects an already-validated
    request and does not check the spec itself, so validate_request is
    called here directly. It raises on the first failure and the app-level
    SurveyToolError handler turns that into a proper 4xx — unlike the
    projection endpoint, an invalid spec here is a real error, since the
    caller has asked for figures that cannot be computed.
    """
    session = _require_session(session_id)
    question_ids = request.question_ids
    if question_ids is None:
        # Same set the existing /demographics endpoint offers.
        question_ids = [
            q.qid for q in session.survey.questions
            if q.base_eligible and not q.is_demographic
        ]
    return _compute_breaks_results(session, request.break_spec, request.filter_spec, question_ids)


@app.post("/api/session/{session_id}/breaks-figure")
async def post_breaks_figure(session_id: str, request: BreaksFigureRequest) -> dict:
    """Serve one Cross-tab chart as a serialized Plotly figure for the
    screen. Built by the same _compute_breaks_results + build_figure calls
    /breaks-export rasterizes, so the on-screen chart and its PNG are one
    figure and cannot drift apart (the Charts tab's /charts guarantee,
    extended to Cross-tab). build_figure refuses a non-permitted chart type.
    """
    session = _require_session(session_id)
    question_result = _compute_breaks_results(
        session, request.break_spec, request.filter_spec, [request.question_id]
    )[0]
    fig = build_figure(
        question_result,
        request.chart_type,
        break_spec=request.break_spec.dimensions,
        filter_spec=request.filter_spec.selections,
        swap_axes=request.swap_axes,
    )
    return {"figure": fig.to_plotly_json()}


@app.post("/api/session/{session_id}/breaks-export")
async def post_breaks_export(session_id: str, request: ExportRequest):
    """Render one break/filter chart to a PNG via the Plotly/kaleido renderer
    (build plan section 11) and return the image file.

    Follows the same pipeline post_crosstab already uses (validate_request ->
    compute_breaks_crosstab -> attach_chart_permissions), scoped to the
    single requested question_id, then hands the resulting QuestionResult to
    plotly_renderer.build_figure. build_figure itself refuses (raising
    SurveyToolError/INTERNAL, mapped to a 500 by the app-level handler) a
    chart_type that isn't `permitted=True` in that result's permitted_charts
    -- this endpoint does not duplicate that check, since plotly_renderer is
    the layer that owns it (see plotly_renderer.build_figure's docstring).

    Routed at /breaks-export rather than /export because POST
    /api/session/{id}/export is already taken by the legacy Charts tab's
    own export (now Plotly-based, like this one), which must keep working
    unchanged.

    Returns the rendered PNG directly (FileResponse), rather than a
    manifest/out_dir pair like the legacy /export endpoint: ExportRequest
    carries no out_dir for this endpoint to write into, and a single chart
    is a single file, so there is no manifest to build.
    """
    session = _require_session(session_id)
    question_result = _compute_breaks_results(
        session, request.break_spec, request.filter_spec, [request.question_id]
    )[0]

    fig = build_figure(
        question_result,
        request.chart_type,
        break_spec=request.break_spec.dimensions,
        filter_spec=request.filter_spec.selections,
        swap_axes=request.swap_axes,
    )

    out_path = Path(tempfile.gettempdir()) / f"breaks-export-{uuid.uuid4()}.png"
    rasterize(fig, out_path)

    return FileResponse(
        out_path,
        media_type="image/png",
        filename=f"{question_result.question_id}-{request.chart_type.value}.png",
        background=BackgroundTask(out_path.unlink, missing_ok=True),
    )


@app.post("/api/session/{session_id}/breaks-export-bulk")
async def post_breaks_export_bulk(session_id: str, request: BulkExportRequest):
    """Export every question_id in `request.question_ids` as a PNG, for the
    same break/filter/chart_type combination, into `request.out_dir` --
    the Cross-tab equivalent of the legacy Charts tab's existing bulk
    /export (Item D). No new rendering logic: loops build_figure/rasterize
    per question_id, exactly what /breaks-export already does per-call.
    """
    session = _require_session(session_id)
    results = _compute_breaks_results(
        session, request.break_spec, request.filter_spec, request.question_ids
    )

    out_dir = Path(request.out_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SurveyToolError(
            ErrorCode.INTERNAL,
            "The export could not be saved to the chosen location.",
            detail=str(exc),
            next_action="Choose a different export location and try again.",
        ) from exc

    exported = []
    skipped = []
    for question_result in results:
        # Not every question can render as every chart type, and "Export all"
        # sends the whole survey at whichever chart type is currently on
        # screen -- so a mixed batch is the normal case, not an error.
        # build_figure raises for a non-permitted combination, which would
        # abort the entire batch and export nothing; check the same
        # permitted_charts list it checks internally (populated above by
        # attach_chart_permissions) so an unsupported question is recorded as
        # a skip and the rest of the batch still completes.
        permission = next(
            (p for p in question_result.permitted_charts if p.chart_type is request.chart_type),
            None,
        )
        if permission is None or not permission.permitted:
            skipped.append({
                "question_id": question_result.question_id,
                "reason": (
                    permission.reason if permission is not None and permission.reason
                    else "This question can't be shown as this chart type."
                ),
            })
            continue

        fig = build_figure(
            question_result, request.chart_type,
            break_spec=request.break_spec.dimensions,
            filter_spec=request.filter_spec.selections,
            swap_axes=request.swap_axes,
        )
        filename = f"{question_result.question_id}-{request.chart_type.value}.png"
        rasterize(fig, out_dir / filename)
        exported.append({"question_id": question_result.question_id, "filename": filename})

    return {"exported": exported, "skipped": skipped, "out_dir": request.out_dir}


app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")

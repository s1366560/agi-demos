"""Compatibility facade for canonical Cloud run authority routes."""

from fastapi import APIRouter

from .plans import _execute_approved_plan
from .run_authority_common import _explicit_change_payloads, _load_scoped_run
from .run_input_authority import (
    _PROMOTED_RUN_TASKS,
    _RUN_INPUT_DISPATCH_LEASE,
    RedisControlChannel,
    _canonical_hash,
    _dispatch_lease_is_active,
    _dispatch_persisted_steer,
    _input_ack,
    _input_receipt,
    _promotion_response,
    _run_input_dispatch_rejection,
    _validate_run_input_authorities,
    create_run_input,
    list_run_inputs,
    promote_run_input,
    router as run_input_router,
)
from .run_review_authority import (
    _change_file_from_payload,
    get_active_run,
    get_latest_run,
    get_run_changes,
    get_run_summary,
    router as run_review_router,
)

router = APIRouter()
router.include_router(run_input_router)
router.include_router(run_review_router)

__all__ = [
    "_PROMOTED_RUN_TASKS",
    "_RUN_INPUT_DISPATCH_LEASE",
    "RedisControlChannel",
    "_canonical_hash",
    "_change_file_from_payload",
    "_dispatch_lease_is_active",
    "_dispatch_persisted_steer",
    "_execute_approved_plan",
    "_explicit_change_payloads",
    "_input_ack",
    "_input_receipt",
    "_load_scoped_run",
    "_promotion_response",
    "_run_input_dispatch_rejection",
    "_validate_run_input_authorities",
    "create_run_input",
    "get_active_run",
    "get_latest_run",
    "get_run_changes",
    "get_run_summary",
    "list_run_inputs",
    "promote_run_input",
    "router",
]

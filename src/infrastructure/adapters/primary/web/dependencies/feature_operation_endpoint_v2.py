"""Preserve FastAPI signatures while guarding declared operations before endpoint effects."""

from collections.abc import Callable, Mapping
from functools import wraps
from inspect import Parameter, Signature, isawaitable
from typing import Any, cast

from fastapi import Depends, HTTPException, Request
from fastapi.dependencies.utils import get_typed_signature
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    get_current_user_from_header_or_query,
)
from src.infrastructure.adapters.primary.web.dependencies.feature_operation_scope_v2 import (
    feature_operation_scopes_v2,
)
from src.infrastructure.adapters.primary.web.dependencies.feature_operation_v2 import (
    require_feature_operation_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.feature_operations import FeatureOperationOwnerV2
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error


def guard_feature_endpoint_v2(
    endpoint: Callable[..., Any], owner: FeatureOperationOwnerV2
) -> Callable[..., Any]:
    signature = get_typed_signature(endpoint)
    parameters = list(signature.parameters.values())
    request_name = next((p.name for p in parameters if p.annotation is Request), None)
    db_name = next((p.name for p in parameters if p.annotation is AsyncSession), None)
    injected: dict[str, tuple[Any, Any]] = {}
    if db_name is None:
        injected["_feature_db_v2"] = (AsyncSession, Depends(get_db))
    if request_name is None:
        injected["_feature_request_v2"] = (Request, Parameter.empty)
    if "current_user" not in signature.parameters:
        injected["_feature_user_v2"] = (User, Depends(get_current_user_from_header_or_query))
    for name, (annotation, default) in injected.items():
        parameters.append(
            Parameter(name, Parameter.KEYWORD_ONLY, annotation=annotation, default=default)
        )

    @wraps(endpoint)
    async def guarded(**arguments: object) -> object:
        request = cast(
            Request,
            arguments[request_name] if request_name else arguments.pop("_feature_request_v2"),
        )
        db = arguments[db_name] if db_name else arguments.pop("_feature_db_v2")
        current_user = arguments.pop("_feature_user_v2", arguments.get("current_user"))
        await admit_feature_endpoint_v2(
            request=request,
            db=cast(AsyncSession, db),
            current_user=cast(User, current_user),
            owner=owner,
            arguments=arguments,
        )
        result = endpoint(**arguments)
        return await result if isawaitable(result) else result

    cast(Any, guarded).__signature__ = Signature(
        parameters=parameters, return_annotation=signature.return_annotation
    )
    cast(Any, guarded).__feature_operation_owner_v2 = owner
    return guarded


async def admit_feature_endpoint_v2(
    *,
    request: Request,
    db: AsyncSession,
    current_user: User,
    owner: FeatureOperationOwnerV2,
    arguments: Mapping[str, Any],
) -> None:
    """Shared admission for ordinary endpoints and body-streaming proxy routes."""
    try:
        scopes = await feature_operation_scopes_v2(
            db=db,
            current_user=current_user,
            owner=owner,
            arguments=arguments,
        )
        feature_ids = list(owner.feature_ids)
        for parameter, field, feature_id in owner.payload_field_owners:
            payload = arguments.get(parameter)
            if isinstance(payload, BaseModel) and field in payload.model_fields_set:
                feature_ids.append(feature_id)
        for scope in scopes:
            await require_feature_operation_v2(
                request=request,
                db=db,
                current_user=current_user,
                feature_ids=tuple(feature_ids),
                scope=scope,
            )
    except RuntimeV2Error as error:
        status_code = 403
        if error.code == "scope_resource_unavailable":
            status_code = 404
        elif error.code in {
            "scoped_runtime_missing",
            "feature_scope_unavailable",
            "scope_not_admitted",
        }:
            status_code = 503
        raise HTTPException(
            status_code,
            detail={
                "code": error.code,
                "message": _("This feature is unavailable in the current scope"),
            },
        ) from error

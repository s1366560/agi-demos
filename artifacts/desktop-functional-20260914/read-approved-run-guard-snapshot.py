import asyncio
import json
from pathlib import Path
from sqlalchemy import text
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import AgentRunAuthorityModel, AgentPlanRunModel, Conversation, User

async def main():
    async with async_session_factory() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        run = await db.get(AgentRunAuthorityModel, "0b8b7bed-8822-47e5-af89-188d98d1f2ee")
        assert run is not None and run.conversation_id == "97339e6b-5213-5f42-91ef-30187c315145"
        assert run.project_id == "738ace12-0d21-48ca-847d-cd0c2802816d"
        source = await db.get(AgentPlanRunModel, run.plan_run_id)
        conversation = await db.get(Conversation, run.conversation_id)
        user = await db.get(User, conversation.user_id)
        approval = run.authorization_snapshot.get("approval_request") or {}
        request = approval.get("request") or {}
        data = {
            "run_id": run.id, "kind":run.run_kind, "status":run.status,
            "profile":run.permission_profile, "plan_run_id":run.plan_run_id,
            "plan_version_id":run.plan_version_id,
            "source_status":source.status if source else None,
            "source_id_matches":bool(source and source.id == run.id),
            "source_profile_matches":bool(source and source.permission_profile == run.permission_profile),
            "source_approval_matches":bool(source and source.authorization_snapshot.get("approval_request") == approval),
            "approval_schema":approval.get("schema_version"),
            "approval_user_matches":approval.get("user_id") == conversation.user_id,
            "approval_tenant_matches":approval.get("tenant_id") == run.tenant_id,
            "approval_request_profile":request.get("permission_profile"),
            "approval_request_plan_matches":request.get("plan_version_id") == run.plan_version_id,
            "approval_request_conversation_matches":request.get("conversation_id") == run.conversation_id,
            "user_active":user.is_active,
            "cancel_receipt_present": bool(run.authorization_snapshot.get("cancellation_receipt")),
        }
        Path("artifacts/desktop-functional-20260914/cloud-native-approved-guard-db-snapshot.json").write_text(json.dumps(data,indent=2))
        print(json.dumps(data))
try:
    asyncio.run(main())
except Exception as exc:
    print(type(exc).__name__)
    raise SystemExit(1)

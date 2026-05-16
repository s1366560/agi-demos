from src.domain.model.agent import ExecutionPlan, ExecutionStep, PlanSnapshot


def test_create_snapshot_returns_plan_with_serializable_snapshot() -> None:
    plan = ExecutionPlan(
        id="plan-1",
        conversation_id="conv-1",
        user_query="Find related memories",
        steps=[
            ExecutionStep(
                step_id="step-1",
                description="Search memory graph",
                tool_name="memory_search",
                tool_input={"query": "related memories"},
            )
        ],
    )

    updated = plan.create_snapshot("before-execute", "State before running step 1")

    assert updated is not plan
    assert plan.snapshot is None
    assert isinstance(updated.snapshot, PlanSnapshot)
    assert updated.snapshot.plan_id == "plan-1"
    assert updated.snapshot.name == "before-execute"
    assert updated.snapshot.description == "State before running step 1"
    assert updated.snapshot.plan_state["id"] == "plan-1"
    assert updated.snapshot.plan_state["steps"][0]["step_id"] == "step-1"
    assert updated.snapshot.to_dict()["created_at"]

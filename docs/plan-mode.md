# Plan Mode

## Overview

Plan Mode is an advanced execution mode for the MemStack agent that uses pre-generated execution plans with automatic reflection and adjustment capabilities.

## When Plan Mode is Triggered

Plan Mode is automatically triggered for:

1. **Complex Queries**: Multi-step queries that require planning
2. **User Request**: Explicit user request to create a plan
3. **Configuration**: Agent configuration settings

## How Plan Mode Works

### 1. Plan Generation

The agent uses LLM to generate a structured execution plan with:
- **Steps**: Individual tasks to accomplish
- **Dependencies**: Order constraints between steps
- **Tools**: Required tools for each step
- **Estimates**: Expected duration and outputs

Example plan:
```json
{
  "steps": [
    {
      "description": "Search memory for Python information",
      "tool_name": "MemorySearch",
      "input_data": {"query": "Python"},
      "dependencies": []
    },
    {
      "description": "Summarize findings",
      "tool_name": "Summary",
      "input_data": {"content": "$previous_result"},
      "dependencies": ["step-1"]
    }
  ]
}
```

### 2. Plan Execution

The executor runs steps in order, respecting dependencies:
- **Sequential Mode**: Steps run one at a time (default)
- **Parallel Mode**: Independent steps run simultaneously

### 3. Reflection

After execution, the reflector analyzes:
- **Goal Achievement**: Was the original goal met?
- **Error Analysis**: Why did steps fail?
- **Adjustment Suggestions**: What changes are needed?

### 4. Adjustment

Based on reflection, the plan may be adjusted:
- **MODIFY**: Change step parameters
- **RETRY**: Retry failed step with new settings
- **SKIP**: Skip unnecessary steps
- **ADD_BEFORE/ADD_AFTER**: Insert new steps
- **REPLACE**: Replace step entirely

### 5. Repeat

The cycle continues until:
- Plan is complete
- Plan fails critically
- Max reflection cycles reached

## Configuration

```python
# In agent configuration
PLAN_MODE_CONFIG = {
    "max_reflection_cycles": 3,
    "reflection_enabled": True,
    "parallel_execution": False,
    "max_parallel_steps": 3,
}
```

## SSE Events

Plan Mode emits the following events:

| Event | Description |
|-------|-------------|
| `plan_execution_start` | Plan execution begins |
| `plan_step_ready` | Step is ready to execute |
| `plan_step_complete` | Step execution finished |
| `plan_step_skipped` | Step was skipped |
| `plan_execution_complete` | Plan execution finished |
| `reflection_complete` | Reflection analysis done |
| `adjustment_applied` | Adjustments were applied |

## Frontend Display

The Plan Mode UI includes:

1. **ExecutionPlanProgress**: Progress bar with step counts
2. **PlanModeViewer**: Detailed view with all steps
3. **Step Status Indicators**: Visual status for each step
4. **Reflection Results**: Display reflection analysis

## Best Practices

1. **For Complex Queries**: Use Plan Mode for multi-step tasks
2. **Set Realistic Limits**: Configure appropriate max_reflection_cycles
3. **Monitor Events**: Watch SSE events for real-time updates
4. **Handle Errors**: Implement proper error handling for failures

## Troubleshooting

### Plan Stuck in "Executing"

- Check if reflection is enabled
- Verify max_reflection_cycles limit
- Look for dependency cycles

### Steps Failing Repeatedly

- Check tool availability
- Verify input parameters
- Consider using SKIP adjustment

### High Memory Usage

- Reduce max_reflection_cycles
- Disable reflection for simple tasks
- Clear old plan snapshots

## API Reference

### PlanGenerator

```python
plan = await generator.generate_plan(
    conversation_id="conv-1",
    query="Search for Python memories",
    context="Optional context",
    reflection_enabled=True,
    max_reflection_cycles=3,
)
```

### PlanExecutor

```python
result = await executor.execute_plan(
    plan=plan,
    abort_signal=None,  # Optional asyncio.Event
)
```

### PlanReflector

```python
reflection = await reflector.reflect(plan)
```

### PlanAdjuster

```python
adjusted_plan = adjuster.apply_adjustments(
    plan=plan,
    adjustments=reflection.adjustments,
)
```

### PlanModeOrchestrator

```python
result = await orchestrator.execute_plan(
    plan=plan,
    abort_signal=abort_signal,
)
```

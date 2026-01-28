# Plan Mode Architecture

## Overview

Plan Mode is a sophisticated execution mode that uses pre-generated execution plans with reflection and adjustment capabilities.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         Plan Mode Orchestrator                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Generator│  │ Executor │  │Reflector │  │ Adjuster │       │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
│       │            │            │            │                 │
└───────┼────────────┼────────────┼────────────┼─────────────────┘
        │            │            │            │
        ▼            ▼            ▼            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Domain Layer                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │ExecutionPlan │  │ ExecutionStep│  │ReflectionResult│       │
│  └──────────────┘  └──────────────┘  └──────────────┘        │
│  ┌──────────────┐  ┌──────────────┐                           │
│  │PlanSnapshot  │  │StepAdjustment│                           │
│  └──────────────┘  └──────────────┘                           │
└─────────────────────────────────────────────────────────────────┘
        │            │            │            │
        ▼            ▼            ▼            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Infrastructure Layer                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │   LLM    │  │ Session  │  │   Redis  │  │  Events  │     │
│  │  Client  │  │Processor │  │  Queue   │  │ Emitter  │     │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

### PlanGenerator

- **Purpose**: Generate execution plans using LLM
- **Input**: User query, context, available tools
- **Output**: ExecutionPlan with steps and dependencies
- **Error Handling**: Falls back to basic plan on LLM failure

### PlanExecutor

- **Purpose**: Execute plans sequentially or in parallel
- **Input**: ExecutionPlan, abort signal
- **Output**: Updated ExecutionPlan with results
- **Features**:
  - Respects step dependencies
  - Emits SSE events for progress
  - Handles abort signals

### PlanReflector

- **Purpose**: Analyze execution and suggest improvements
- **Input**: ExecutionPlan (post-execution)
- **Output**: ReflectionResult with assessment and adjustments
- **Error Handling**: Returns safe default on LLM failure

### PlanAdjuster

- **Purpose**: Apply adjustments to plans (immutable)
- **Input**: ExecutionPlan, StepAdjustments
- **Output**: New ExecutionPlan with adjustments applied
- **Operations**: MODIFY, RETRY, SKIP, ADD_BEFORE, ADD_AFTER, REPLACE

### PlanModeOrchestrator

- **Purpose**: Coordinate complete workflow
- **Workflow**: Generate -> Execute -> Reflect -> Adjust -> Repeat
- **Features**:
  - Enforces max_reflection_cycles
  - Handles abort signals
  - Emits orchestration events

## Data Flow

### Plan Generation Flow

```
User Query
    │
    ▼
┌─────────────┐
│PlanGenerator│
└──────┬──────┘
       │
       ├─► Build prompts (system + user)
       │
       ├─► Call LLM
       │
       ├─► Parse JSON response
       │
       └─► Create ExecutionPlan
           │
           ├─► Create ExecutionSteps
           ├─► Map dependencies
           └─► Validate tool availability
```

### Execution Flow

```
ExecutionPlan
    │
    ▼
┌─────────────┐
│PlanExecutor │
└──────┬──────┘
       │
       ├─► Mark plan as EXECUTING
       │
       ├─► Get ready steps (respect deps)
       │
       ├─► For each ready step:
       │       ├─► Mark step as RUNNING
       │       ├─► Execute tool (or think)
       │       ├─► Mark step as COMPLETE/FAILED
       │       └─► Emit step event
       │
       └─► Determine final status
           ├─► All complete -> COMPLETED
           ├─► Any failed -> FAILED
           └─► Aborted -> CANCELLED
```

### Reflection Flow

```
ExecutionPlan (post-execution)
    │
    ▼
┌─────────────┐
│PlanReflector│
└──────┬──────┘
       │
       ├─► Build reflection prompt
       │   ├─► Include step results
       │   ├─► Include failed steps
       │   └─► Include current status
       │
       ├─► Call LLM
       │
       ├─► Parse reflection response
       │
       └─► Create ReflectionResult
           ├─► Assessment (ON_TRACK, etc.)
           ├─► Reasoning
           └─► Adjustments (if any)
```

### Adjustment Flow

```
ExecutionPlan + Adjustments
    │
    ▼
┌─────────────┐
│PlanAdjuster │
└──────┬──────┘
       │
       └─► For each adjustment:
           ├─► MODIFY: Update tool_input
           ├─► RETRY: Reset to PENDING, new input
           ├─► SKIP: Mark as SKIPPED
           ├─► ADD_BEFORE: Insert before step
           ├─► ADD_AFTER: Insert after step
           └─► REPLACE: Replace step entirely
               │
               └─► Return NEW ExecutionPlan (immutable)
```

## State Management

### ExecutionPlan States

```
DRAFT ──► APPROVED ──► EXECUTING
                          │
                          ├─► PAUSED
                          ├─► COMPLETED
                          ├─► FAILED
                          └─► CANCELLED
```

### ExecutionStep States

```
PENDING ──► RUNNING ──► COMPLETED
                    │
                    └─► FAILED

PENDING ──► SKIPPED
PENDING ──► CANCELLED
```

### Reflection Assessments

```
┌─────────────────────────────────────┐
│         Terminal States             │
│  ┌─────────┐      ┌─────────┐      │
│  │ COMPLETE│      │ FAILED  │      │
│  └─────────┘      └─────────┘      │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│      Non-Terminal States            │
│  ┌─────────┐  ┌───────┐  ┌──────┐  │
│  │ON_TRACK │  │NEEDS_  │  │OFF_  │  │
│  │         │  │ADJUST. │  │TRACK │  │
│  └─────────┘  └───────┘  └──────┘  │
└─────────────────────────────────────┘
```

## Event Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        SSE Events                                │
│                                                                   │
│  plan_execution_start ──► plan_step_ready ──►                  │
│       │                      │                                  │
│       │                      ▼                                  │
│       │              plan_step_complete ──►                     │
│       │                      │                                  │
│       │                      ▼                                  │
│       │              reflection_complete ──►                    │
│       │                      │                                  │
│       │              [adjustment?] ──► adjustment_applied       │
│       │                      │                                  │
│       └──────────────────────┼──────────────────────────┐      │
│                              ▼                          ▼      │
│                    plan_execution_complete ◄──────────────────┘
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Immutability Pattern

All plan modifications follow immutability:

```python
# BAD: Mutation
plan.status = ExecutionPlanStatus.COMPLETED

# GOOD: Immutable update
updated_plan = plan.mark_completed()
```

This ensures:
- Thread safety
- Easy rollback
- Predictable state changes
- Better testing

## Error Handling Strategy

### LLM Failures

- **Plan Generation**: Use fallback plan
- **Reflection**: Use safe default (ON_TRACK)
- **Adjustment**: Skip adjustment, continue execution

### Execution Failures

- **Step Failed**: Mark step as failed, trigger reflection
- **Tool Unavailable**: Skip step or use alternative
- **Dependency Cycle**: Detect and report error

### Orchestrator Failures

- **Max Cycles**: Stop and return current state
- **Abort Signal**: Gracefully stop execution
- **Critical Error**: Mark plan as FAILED

## Testing Strategy

### Unit Tests

- **PlanGenerator**: Prompt building, JSON parsing, fallback
- **PlanExecutor**: Step execution, dependency handling
- **PlanReflector**: Response parsing, default creation
- **PlanAdjuster**: Each adjustment type
- **Orchestrator**: Workflow coordination

### Integration Tests

- **End-to-End**: Complete Plan Mode execution
- **Reflection Cycles**: Multiple adjustments
- **Error Handling**: LLM failures, step failures

### Frontend Tests

- **Component Rendering**: Display plans, steps, progress
- **Event Handling**: Update UI on SSE events
- **User Interaction**: Approve/reject adjustments

## Performance Considerations

- **LLM Calls**: Minimize through caching
- **Parallel Execution**: Enable for independent steps
- **Event Emission**: Batch when possible
- **Reflection**: Disable for simple tasks

## Security Considerations

- **Tool Input Validation**: Sanitize all inputs
- **Permission Checks**: Verify tool access
- **Resource Limits**: Enforce max steps/cycles
- **Audit Logging**: Track all plan modifications

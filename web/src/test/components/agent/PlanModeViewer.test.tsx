/**
 * Tests for PlanModeViewer component
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { PlanModeViewer } from "../../../components/agent/PlanModeViewer";
import { ExecutionPlan, ExecutionPlanStatus, ReflectionResult } from "../../../types/agent";

describe("PlanModeViewer", () => {
  it("renders no plan message when plan is null", () => {
    render(<PlanModeViewer plan={null} />);
    expect(screen.getByText("No execution plan available")).toBeInTheDocument();
  });

  it("renders plan header with basic info", () => {
    const plan: ExecutionPlan = {
      id: "plan-12345678",
      conversation_id: "conv-1",
      user_query: "Search for Python memories",
      steps: [],
      status: "draft" as ExecutionPlanStatus,
      reflection_enabled: true,
      max_reflection_cycles: 3,
      completed_steps: [],
      failed_steps: [],
      progress_percentage: 0,
      is_complete: false,
    };

    render(<PlanModeViewer plan={plan} />);

    expect(screen.getByText("Execution Plan")).toBeInTheDocument();
    expect(screen.getByText(/plan-123/)).toBeInTheDocument();
    expect(screen.getByText("Search for Python memories")).toBeInTheDocument();
    expect(screen.getByText("Enabled")).toBeInTheDocument();
  });

  it("renders plan steps", () => {
    const plan: ExecutionPlan = {
      id: "plan-1",
      conversation_id: "conv-1",
      user_query: "Test query",
      steps: [
        {
          step_id: "step-1",
          description: "Search memory",
          tool_name: "MemorySearch",
          tool_input: { query: "Python" },
          dependencies: [],
          status: "completed",
          result: "Found 5 memories",
        },
        {
          step_id: "step-2",
          description: "Summarize results",
          tool_name: "Summary",
          tool_input: {},
          dependencies: ["step-1"],
          status: "pending",
        },
      ],
      status: "executing" as ExecutionPlanStatus,
      reflection_enabled: true,
      max_reflection_cycles: 3,
      completed_steps: ["step-1"],
      failed_steps: [],
      progress_percentage: 50,
      is_complete: false,
    };

    render(<PlanModeViewer plan={plan} />);

    expect(screen.getByText("Steps (2)")).toBeInTheDocument();
    expect(screen.getByText(/Step 1: Search memory/)).toBeInTheDocument();
    expect(screen.getByText(/Step 2: Summarize results/)).toBeInTheDocument();
  });

  it("renders reflection badge when reflection is provided", () => {
    const plan: ExecutionPlan = {
      id: "plan-1",
      conversation_id: "conv-1",
      user_query: "Test query",
      steps: [],
      status: "executing" as ExecutionPlanStatus,
      reflection_enabled: true,
      max_reflection_cycles: 3,
      completed_steps: [],
      failed_steps: [],
      progress_percentage: 0,
      is_complete: false,
    };

    const reflection: ReflectionResult = {
      assessment: "on_track",
      reasoning: "Everything is progressing well",
      adjustments: [],
      is_terminal: false,
      reflection_metadata: {},
    };

    render(<PlanModeViewer plan={plan} reflection={reflection} />);

    expect(screen.getByText("on track")).toBeInTheDocument();
    expect(screen.getByText("Everything is progressing well")).toBeInTheDocument();
  });

  it("renders reflection with needs_adjustment assessment", () => {
    const plan: ExecutionPlan = {
      id: "plan-1",
      conversation_id: "conv-1",
      user_query: "Test query",
      steps: [],
      status: "executing" as ExecutionPlanStatus,
      reflection_enabled: true,
      max_reflection_cycles: 3,
      completed_steps: [],
      failed_steps: [],
      progress_percentage: 0,
      is_complete: false,
    };

    const reflection: ReflectionResult = {
      assessment: "needs_adjustment",
      reasoning: "Step failed, needs retry",
      adjustments: [
        {
          step_id: "step-1",
          adjustment_type: "retry",
          reason: "Timeout occurred",
        },
      ],
      is_terminal: false,
      reflection_metadata: {},
    };

    render(<PlanModeViewer plan={plan} reflection={reflection} />);

    expect(screen.getByText("needs adjustment")).toBeInTheDocument();
    expect(screen.getByText("Step failed, needs retry")).toBeInTheDocument();
  });

  it("renders step with completed status", () => {
    const plan: ExecutionPlan = {
      id: "plan-1",
      conversation_id: "conv-1",
      user_query: "Test",
      steps: [
        {
          step_id: "step-1",
          description: "Test step",
          tool_name: "TestTool",
          tool_input: {},
          dependencies: [],
          status: "completed",
          result: "Success!",
        },
      ],
      status: "completed" as ExecutionPlanStatus,
      reflection_enabled: false,
      max_reflection_cycles: 3,
      completed_steps: ["step-1"],
      failed_steps: [],
      progress_percentage: 100,
      is_complete: true,
    };

    render(<PlanModeViewer plan={plan} />);

    expect(screen.getByText(/Test step/)).toBeInTheDocument();
    expect(screen.getByText("Success!")).toBeInTheDocument();
  });

  it("renders step with failed status and error", () => {
    const plan: ExecutionPlan = {
      id: "plan-1",
      conversation_id: "conv-1",
      user_query: "Test",
      steps: [
        {
          step_id: "step-1",
          description: "Failing step",
          tool_name: "TestTool",
          tool_input: {},
          dependencies: [],
          status: "failed",
          error: "Connection timeout",
        },
      ],
      status: "failed" as ExecutionPlanStatus,
      reflection_enabled: false,
      max_reflection_cycles: 3,
      completed_steps: [],
      failed_steps: ["step-1"],
      progress_percentage: 0,
      is_complete: false,
    };

    render(<PlanModeViewer plan={plan} />);

    expect(screen.getByText(/Failing step/)).toBeInTheDocument();
    expect(screen.getByText("Connection timeout")).toBeInTheDocument();
  });

  it("renders empty steps message", () => {
    const plan: ExecutionPlan = {
      id: "plan-1",
      conversation_id: "conv-1",
      user_query: "Test",
      steps: [],
      status: "draft" as ExecutionPlanStatus,
      reflection_enabled: false,
      max_reflection_cycles: 3,
      completed_steps: [],
      failed_steps: [],
      progress_percentage: 100,
      is_complete: true,
    };

    render(<PlanModeViewer plan={plan} />);

    expect(screen.getByText("No steps in this plan")).toBeInTheDocument();
  });

  it("renders step dependencies", () => {
    const plan: ExecutionPlan = {
      id: "plan-1",
      conversation_id: "conv-1",
      user_query: "Test",
      steps: [
        {
          step_id: "step-2",
          description: "Dependent step",
          tool_name: "TestTool",
          tool_input: {},
          dependencies: ["step-1"],
          status: "pending",
        },
      ],
      status: "draft" as ExecutionPlanStatus,
      reflection_enabled: false,
      max_reflection_cycles: 3,
      completed_steps: [],
      failed_steps: [],
      progress_percentage: 0,
      is_complete: false,
    };

    render(<PlanModeViewer plan={plan} />);

    expect(screen.getByText(/Dependencies: step-1/)).toBeInTheDocument();
  });

  it("renders timestamps when available", () => {
    const startedAt = new Date("2024-01-15T10:30:00Z").toISOString();
    const completedAt = new Date("2024-01-15T10:35:00Z").toISOString();

    const plan: ExecutionPlan = {
      id: "plan-1",
      conversation_id: "conv-1",
      user_query: "Test",
      steps: [],
      status: "completed" as ExecutionPlanStatus,
      reflection_enabled: false,
      max_reflection_cycles: 3,
      completed_steps: [],
      failed_steps: [],
      progress_percentage: 100,
      is_complete: true,
      started_at: startedAt,
      completed_at: completedAt,
    };

    render(<PlanModeViewer plan={plan} />);

    expect(screen.getByText(/Started:/)).toBeInTheDocument();
    expect(screen.getByText(/Completed:/)).toBeInTheDocument();
  });
});

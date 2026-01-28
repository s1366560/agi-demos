/**
 * Tests for ExecutionPlanProgress component
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ExecutionPlanProgress } from "../../../components/agent/ExecutionPlanProgress";
import { ExecutionPlan, ExecutionPlanStatus } from "../../../types/agent";

describe("ExecutionPlanProgress", () => {
  it("renders no plan message when plan is null", () => {
    render(<ExecutionPlanProgress plan={null} />);
    expect(screen.getByText("No execution plan")).toBeInTheDocument();
  });

  it("renders progress with draft status", () => {
    const plan: ExecutionPlan = {
      id: "plan-1",
      conversation_id: "conv-1",
      user_query: "Test query",
      steps: [
        {
          step_id: "step-1",
          description: "Test step",
          tool_name: "TestTool",
          tool_input: {},
          dependencies: [],
          status: "pending",
        },
      ],
      status: "draft" as ExecutionPlanStatus,
      reflection_enabled: true,
      max_reflection_cycles: 3,
      completed_steps: [],
      failed_steps: [],
      progress_percentage: 0,
      is_complete: false,
    };

    render(<ExecutionPlanProgress plan={plan} />);

    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(screen.getByText(/0 \/ 1 steps/)).toBeInTheDocument();
  });

  it("renders progress with completed steps", () => {
    const plan: ExecutionPlan = {
      id: "plan-1",
      conversation_id: "conv-1",
      user_query: "Test query",
      steps: [
        {
          step_id: "step-1",
          description: "Test step 1",
          tool_name: "TestTool",
          tool_input: {},
          dependencies: [],
          status: "completed",
        },
        {
          step_id: "step-2",
          description: "Test step 2",
          tool_name: "TestTool",
          tool_input: {},
          dependencies: [],
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

    render(<ExecutionPlanProgress plan={plan} />);

    expect(screen.getByText(/1 \/ 2 steps/)).toBeInTheDocument();
    expect(screen.getByText("Completed: 1")).toBeInTheDocument();
    expect(screen.getByText("Failed: 0")).toBeInTheDocument();
    expect(screen.getByText("Remaining: 1")).toBeInTheDocument();
  });

  it("renders progress with failed steps", () => {
    const plan: ExecutionPlan = {
      id: "plan-1",
      conversation_id: "conv-1",
      user_query: "Test query",
      steps: [
        {
          step_id: "step-1",
          description: "Test step",
          tool_name: "TestTool",
          tool_input: {},
          dependencies: [],
          status: "failed",
          error: "Test error",
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

    render(<ExecutionPlanProgress plan={plan} />);

    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("Failed: 1")).toBeInTheDocument();
  });

  it("does not show reflection info when disabled", () => {
    const plan: ExecutionPlan = {
      id: "plan-1",
      conversation_id: "conv-1",
      user_query: "Test query",
      steps: [],
      status: "draft" as ExecutionPlanStatus,
      reflection_enabled: false,
      max_reflection_cycles: 3,
      completed_steps: [],
      failed_steps: [],
      progress_percentage: 0,
      is_complete: true,
    };

    render(<ExecutionPlanProgress plan={plan} />);

    expect(screen.queryByText(/Reflection:/)).not.toBeInTheDocument();
  });

  it("shows reflection info when enabled", () => {
    const plan: ExecutionPlan = {
      id: "plan-1",
      conversation_id: "conv-1",
      user_query: "Test query",
      steps: [],
      status: "draft" as ExecutionPlanStatus,
      reflection_enabled: true,
      max_reflection_cycles: 5,
      completed_steps: [],
      failed_steps: [],
      progress_percentage: 0,
      is_complete: true,
    };

    render(<ExecutionPlanProgress plan={plan} />);

    expect(screen.getByText(/Reflection: 5 max cycles/)).toBeInTheDocument();
  });

  it("renders completed plan with full progress", () => {
    const plan: ExecutionPlan = {
      id: "plan-1",
      conversation_id: "conv-1",
      user_query: "Test query",
      steps: [
        {
          step_id: "step-1",
          description: "Test step",
          tool_name: "TestTool",
          tool_input: {},
          dependencies: [],
          status: "completed",
        },
      ],
      status: "completed" as ExecutionPlanStatus,
      reflection_enabled: true,
      max_reflection_cycles: 3,
      completed_steps: ["step-1"],
      failed_steps: [],
      progress_percentage: 100,
      is_complete: true,
    };

    render(<ExecutionPlanProgress plan={plan} />);

    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText(/1 \/ 1 steps/)).toBeInTheDocument();
  });
});

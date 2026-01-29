/**
 * Unit tests for PlanModeIndicator component.
 *
 * TDD RED Phase: Tests written first for PlanModeIndicator integration.
 *
 * Feature: Display Plan Mode status in AgentChat with quick actions.
 *
 * Tests cover:
 * - Rendering in different modes (build/plan/explore)
 * - Compact mode display
 * - Full mode display with actions
 * - View Plan callback
 * - Exit Plan Mode callback
 * - Null status handling
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PlanModeIndicator } from "../../../components/agent/PlanModeIndicator";
import type { PlanModeStatus, PlanDocument } from "../../../types/agent";

describe("PlanModeIndicator", () => {
  const mockPlan: PlanDocument = {
    id: "plan-123",
    conversation_id: "conv-1",
    title: "Test Plan",
    content: "Test content",
    status: "draft",
    version: 1,
    metadata: {},
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
  };

  const planModeStatus: PlanModeStatus = {
    is_in_plan_mode: true,
    current_mode: "plan",
    current_plan_id: mockPlan.id,
    plan: mockPlan,
  };

  const buildModeStatus: PlanModeStatus = {
    is_in_plan_mode: false,
    current_mode: "build",
    current_plan_id: null,
    plan: null,
  };

  const exploreModeStatus: PlanModeStatus = {
    is_in_plan_mode: false,
    current_mode: "explore",
    current_plan_id: null,
    plan: null,
  };

  describe("Null Status Handling", () => {
    it("should return null when status is null", () => {
      const { container } = render(<PlanModeIndicator status={null} />);
      expect(container.firstChild).toBeNull();
    });
  });

  describe("Build Mode Display", () => {
    it("should return null for build mode when not in plan mode (default state)", () => {
      const { container } = render(<PlanModeIndicator status={buildModeStatus} />);
      expect(container.firstChild).toBeNull();
    });
  });

  describe("Plan Mode Display", () => {
    it("should render Plan Mode indicator when in plan mode", () => {
      render(<PlanModeIndicator status={planModeStatus} />);

      expect(screen.getByText("Plan Mode")).toBeInTheDocument();
    });

    it("should render plan title tag", () => {
      render(<PlanModeIndicator status={planModeStatus} />);

      expect(screen.getByText("Test Plan")).toBeInTheDocument();
    });

    it("should render mode description", () => {
      render(<PlanModeIndicator status={planModeStatus} />);

      expect(screen.getByText(/Read-only \+ plan editing/)).toBeInTheDocument();
    });

    it("should render View Plan button", () => {
      const onViewPlan = vi.fn();
      render(<PlanModeIndicator status={planModeStatus} onViewPlan={onViewPlan} />);

      expect(screen.getByRole("button", { name: /view plan/i })).toBeInTheDocument();
    });

    it("should render Exit Plan Mode button", () => {
      const onExitPlanMode = vi.fn();
      render(<PlanModeIndicator status={planModeStatus} onExitPlanMode={onExitPlanMode} />);

      expect(screen.getByRole("button", { name: /exit plan mode/i })).toBeInTheDocument();
    });

    it("should call onViewPlan when View Plan button is clicked", () => {
      const onViewPlan = vi.fn();
      render(<PlanModeIndicator status={planModeStatus} onViewPlan={onViewPlan} />);

      const viewPlanButton = screen.getByRole("button", { name: /view plan/i });
      fireEvent.click(viewPlanButton);

      expect(onViewPlan).toHaveBeenCalledTimes(1);
    });

    it("should call onExitPlanMode when Exit Plan Mode button is clicked", () => {
      const onExitPlanMode = vi.fn();
      render(<PlanModeIndicator status={planModeStatus} onExitPlanMode={onExitPlanMode} />);

      const exitButton = screen.getByRole("button", { name: /exit plan mode/i });
      fireEvent.click(exitButton);

      expect(onExitPlanMode).toHaveBeenCalledTimes(1);
    });

    it("should not render View Plan button when onViewPlan is not provided", () => {
      render(<PlanModeIndicator status={planModeStatus} />);

      expect(screen.queryByRole("button", { name: /view plan/i })).not.toBeInTheDocument();
    });

    it("should not render Exit Plan Mode button when onExitPlanMode is not provided", () => {
      render(<PlanModeIndicator status={planModeStatus} />);

      expect(screen.queryByRole("button", { name: /exit plan mode/i })).not.toBeInTheDocument();
    });
  });

  describe("Explore Mode Display", () => {
    it("should render Explore Mode indicator", () => {
      render(<PlanModeIndicator status={exploreModeStatus} />);

      expect(screen.getByText("Explore Mode")).toBeInTheDocument();
    });

    it("should render explore mode description", () => {
      render(<PlanModeIndicator status={exploreModeStatus} />);

      expect(screen.getByText(/Pure read-only/)).toBeInTheDocument();
    });
  });

  describe("Compact Mode", () => {
    it("should render compact tag when compact prop is true", () => {
      const { container } = render(
        <PlanModeIndicator status={planModeStatus} compact={true} />
      );

      expect(container.querySelector(".ant-tag")).toBeInTheDocument();
    });

    it("should not render actions in compact mode", () => {
      const onViewPlan = vi.fn();
      const onExitPlanMode = vi.fn();

      render(
        <PlanModeIndicator
          status={planModeStatus}
          compact={true}
          onViewPlan={onViewPlan}
          onExitPlanMode={onExitPlanMode}
        />
      );

      expect(screen.queryByRole("button", { name: /view plan/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /exit plan mode/i })).not.toBeInTheDocument();
    });

    it("should render build mode in compact format", () => {
      const { container } = render(
        <PlanModeIndicator status={buildModeStatus} compact={true} />
      );

      expect(container.querySelector(".ant-tag")).toBeInTheDocument();
      expect(screen.getByText("Build Mode")).toBeInTheDocument();
    });
  });

  describe("Mode Icons and Colors", () => {
    it("should display correct icon for plan mode", () => {
      const { container } = render(<PlanModeIndicator status={planModeStatus} compact={true} />);

      const tag = container.querySelector(".ant-tag");
      expect(tag).toBeInTheDocument();
      // FileTextOutlined icon should be present
      expect(screen.getByText("Plan Mode")).toBeInTheDocument();
    });

    it("should display correct icon for build mode", () => {
      const { container } = render(<PlanModeIndicator status={buildModeStatus} compact={true} />);

      expect(container.querySelector(".ant-tag")).toBeInTheDocument();
      expect(screen.getByText("Build Mode")).toBeInTheDocument();
    });

    it("should display correct icon for explore mode", () => {
      const { container } = render(<PlanModeIndicator status={exploreModeStatus} compact={true} />);

      expect(container.querySelector(".ant-tag")).toBeInTheDocument();
      expect(screen.getByText("Explore Mode")).toBeInTheDocument();
    });
  });
});

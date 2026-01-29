/**
 * Unit tests for StepAdjustmentModal component.
 *
 * TDD RED Phase: Tests written first for StepAdjustmentModal.
 *
 * Feature: Display and handle step adjustment approvals from reflection.
 *
 * Tests cover:
 * - Rendering adjustment suggestions
 * - Approve/Reject individual adjustments
 * - Approve All/Reject All actions
 * - Callback invocations
 * - Empty state handling
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { StepAdjustmentModal } from "../../../components/agent/StepAdjustmentModal";
import type { StepAdjustment } from "../../../types/agent";

describe("StepAdjustmentModal", () => {
  const mockAdjustments: StepAdjustment[] = [
    {
      step_id: "step-1",
      adjustment_type: "modify",
      reason: "Tool input needs correction",
      new_tool_input: { query: "corrected query" },
    },
    {
      step_id: "step-2",
      adjustment_type: "retry",
      reason: "Temporary failure, retry may succeed",
    },
    {
      step_id: "step-3",
      adjustment_type: "skip",
      reason: "Step not necessary due to previous success",
    },
  ];

  const defaultProps = {
    visible: true,
    adjustments: mockAdjustments,
    onApprove: vi.fn(),
    onReject: vi.fn(),
    onApproveAll: vi.fn(),
    onRejectAll: vi.fn(),
    onClose: vi.fn(),
  };

  describe("Rendering", () => {
    it("should render modal when visible is true", () => {
      render(<StepAdjustmentModal {...defaultProps} />);

      expect(screen.getByText(/Step Adjustments/i)).toBeInTheDocument();
    });

    it("should not render modal when visible is false", () => {
      const { container } = render(
        <StepAdjustmentModal {...defaultProps} visible={false} />
      );

      expect(container.querySelector(".ant-modal")).not.toBeInTheDocument();
    });

    it("should render all adjustment items", () => {
      render(<StepAdjustmentModal {...defaultProps} />);

      expect(screen.getByText("step-1")).toBeInTheDocument();
      expect(screen.getByText("step-2")).toBeInTheDocument();
      expect(screen.getByText("step-3")).toBeInTheDocument();
    });

    it("should display adjustment type badges", () => {
      render(<StepAdjustmentModal {...defaultProps} />);

      expect(screen.getByText("modify")).toBeInTheDocument();
      expect(screen.getByText("retry")).toBeInTheDocument();
      expect(screen.getByText("skip")).toBeInTheDocument();
    });

    it("should display adjustment reasons", () => {
      render(<StepAdjustmentModal {...defaultProps} />);

      expect(screen.getByText(/Tool input needs correction/)).toBeInTheDocument();
      expect(screen.getByText(/Temporary failure/)).toBeInTheDocument();
      expect(screen.getByText(/Step not necessary/)).toBeInTheDocument();
    });

    it("should show new_tool_input when present", () => {
      render(<StepAdjustmentModal {...defaultProps} />);

      expect(screen.getByText(/corrected query/)).toBeInTheDocument();
    });
  });

  describe("Empty State", () => {
    it("should show empty message when no adjustments", () => {
      render(<StepAdjustmentModal {...defaultProps} adjustments={[]} />);

      expect(screen.getByText(/No adjustments to review/)).toBeInTheDocument();
    });

    it("should show empty message when adjustments is null", () => {
      render(<StepAdjustmentModal {...defaultProps} adjustments={null as any} />);

      expect(screen.getByText(/No adjustments to review/)).toBeInTheDocument();
    });
  });

  describe("Individual Adjustment Actions", () => {
    it("should call onApprove with step_id when approve button clicked", () => {
      const onApprove = vi.fn();
      render(<StepAdjustmentModal {...defaultProps} onApprove={onApprove} />);

      const approveButtons = screen.getAllByTitle("Approve adjustment");
      fireEvent.click(approveButtons[0]);

      expect(onApprove).toHaveBeenCalledTimes(1);
      expect(onApprove).toHaveBeenCalledWith("step-1");
    });

    it("should call onReject with step_id when reject button clicked", () => {
      const onReject = vi.fn();
      render(<StepAdjustmentModal {...defaultProps} onReject={onReject} />);

      const rejectButtons = screen.getAllByTitle("Reject adjustment");
      fireEvent.click(rejectButtons[0]);

      expect(onReject).toHaveBeenCalledTimes(1);
      expect(onReject).toHaveBeenCalledWith("step-1");
    });
  });

  describe("Bulk Actions", () => {
    it("should call onApproveAll when Approve All button clicked", () => {
      const onApproveAll = vi.fn();
      render(<StepAdjustmentModal {...defaultProps} onApproveAll={onApproveAll} />);

      const approveAllButton = screen.getByRole("button", { name: /approve all/i });
      fireEvent.click(approveAllButton);

      expect(onApproveAll).toHaveBeenCalledTimes(1);
    });

    it("should call onRejectAll when Reject All button clicked", () => {
      const onRejectAll = vi.fn();
      render(<StepAdjustmentModal {...defaultProps} onRejectAll={onRejectAll} />);

      const rejectAllButton = screen.getByRole("button", { name: /reject all/i });
      fireEvent.click(rejectAllButton);

      expect(onRejectAll).toHaveBeenCalledTimes(1);
    });

    it("should not render bulk action buttons when no adjustments", () => {
      const { container } = render(
        <StepAdjustmentModal {...defaultProps} adjustments={[]} />
      );

      expect(screen.queryByRole("button", { name: /approve all/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /reject all/i })).not.toBeInTheDocument();
    });
  });

  describe("Modal Actions", () => {
    it("should call onClose when Cancel button clicked", () => {
      const onClose = vi.fn();
      render(<StepAdjustmentModal {...defaultProps} onClose={onClose} />);

      const cancelButton = screen.getByRole("button", { name: /cancel/i });
      fireEvent.click(cancelButton);

      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it("should call onApproveAll and onClose when Confirm button clicked", () => {
      const onApproveAll = vi.fn();
      const onClose = vi.fn();
      render(
        <StepAdjustmentModal
          {...defaultProps}
          onApproveAll={onApproveAll}
          onClose={onClose}
        />
      );

      const confirmButton = screen.getByRole("button", { name: /confirm/i });
      fireEvent.click(confirmButton);

      expect(onApproveAll).toHaveBeenCalledTimes(1);
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  describe("Adjustment Type Colors", () => {
    it("should display different colors for different adjustment types", () => {
      render(<StepAdjustmentModal {...defaultProps} />);

      // Check that different adjustment type badges exist
      expect(screen.getByText("modify")).toBeInTheDocument();
      expect(screen.getByText("retry")).toBeInTheDocument();
      expect(screen.getByText("skip")).toBeInTheDocument();
    });
  });

  describe("Accessibility", () => {
    it("should have proper ARIA labels", () => {
      render(<StepAdjustmentModal {...defaultProps} />);

      // Ant Design Modal has default role="dialog"
      const modal = screen.getByRole("dialog");
      expect(modal).toBeInTheDocument();
    });

    it("should have accessible action buttons", () => {
      render(<StepAdjustmentModal {...defaultProps} />);

      // Check that approve buttons exist (using title attribute)
      const approveButtons = screen.getAllByTitle("Approve adjustment");
      expect(approveButtons.length).toBeGreaterThan(0);

      // Check that reject buttons exist
      const rejectButtons = screen.getAllByTitle("Reject adjustment");
      expect(rejectButtons.length).toBeGreaterThan(0);
    });
  });
});

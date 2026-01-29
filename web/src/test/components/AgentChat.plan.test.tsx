/**
 * Integration tests for PlanEditor in AgentChat.
 *
 * TDD: Tests written first, implementation to follow.
 * Tests follow RED-GREEN-REFACTOR cycle.
 *
 * This test file ensures that:
 * 1. Plan Tab displays PlanEditor when plan mode is active
 * 2. Plan Tab displays EmptyState when no active plan
 * 3. onUpdate callback is invoked correctly
 * 4. onSubmitForReview callback is invoked correctly
 * 5. onExit callback is invoked correctly
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BrowserRouter } from 'react-router-dom';
import { act } from 'react';
import { vi, beforeEach, afterEach, describe, it, expect } from 'vitest';
import AgentChat from '../../pages/project/AgentChat';
import { usePlanModeStore } from '../../stores/agent/planModeStore';
import { useAgentV3Store } from '../../stores/agentV3';
import type { PlanDocument } from '../../types/agent';

// Mock dependencies
vi.mock('../../services/planService', () => ({
  planService: {
    enterPlanMode: vi.fn(),
    exitPlanMode: vi.fn(),
    getPlan: vi.fn(),
    updatePlan: vi.fn(),
    getPlanModeStatus: vi.fn(),
    submitPlanForReview: vi.fn(),
  },
}));

vi.mock('../../services/sandboxService', () => ({
  sandboxService: {
    listSandboxes: vi.fn(),
    createSandbox: vi.fn(),
  },
}));

// Mock Modal.confirm to auto-confirm in tests
vi.mock('antd', async () => {
  const actual = await vi.importActual<any>('antd');
  return {
    ...actual,
    Modal: {
      ...actual.Modal,
      confirm: vi.fn(({ onOk }) => {
        // Auto-call onOk after a tick to simulate user clicking OK
        setTimeout(() => {
          onOk?.();
        }, 0);
        return Promise.resolve(true);
      }),
    },
  };
});

const mockPlanDocument: PlanDocument = {
  id: 'plan-123',
  title: 'Test Plan',
  content: '# Test Plan\n\nThis is a test plan.',
  status: 'draft',
  version: 1,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
  metadata: {
    explored_files: ['file1.ts', 'file2.ts'],
    critical_files: [],
    conversation_id: 'conv-123',  // Add conversation ID for exit tests
  },
};

const mockPlanModeStatus = {
  is_in_plan_mode: true,
  current_mode: 'plan' as const,
  current_plan_id: 'plan-123',
  plan: mockPlanDocument,
};

describe('AgentChat - Plan Tab Integration', () => {
  beforeEach(() => {
    // Reset stores before each test
    usePlanModeStore.getState().reset();
    useAgentV3Store.getState().reset?.();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  const renderWithRouter = (component: React.ReactElement) => {
    return render(<BrowserRouter>{component}</BrowserRouter>);
  };

  describe('Plan Tab Display', () => {
    it('should display PlanEditor when plan mode is active with current plan', async () => {
      // Setup: Set plan mode state
      usePlanModeStore.setState({
        currentPlan: mockPlanDocument,
        planModeStatus: mockPlanModeStatus,
        planLoading: false,
        planError: null,
      });

      // Setup: Set agent store state
      useAgentV3Store.setState({
        conversations: [],
        activeConversationId: 'conv-123',
        timeline: [],
        messages: [],
        isLoadingHistory: false,
        isStreaming: false,
        workPlan: null,
        executionPlan: null,
        isPlanMode: true,
        showPlanPanel: true,
        pendingDecision: null,
        doomLoopDetected: null,
        error: null,
      });

      await act(async () => {
        renderWithRouter(
          <AgentChat />
        );
      });

      // Assert: PlanEditor should be visible
      // Note: Since RightPanel is collapsible, we need to ensure it's expanded
      await waitFor(() => {
        const planTitle = screen.queryByText('Test Plan');
        expect(planTitle).toBeInTheDocument();
      });
    });

    it('should display EmptyState when no active plan exists', async () => {
      // Setup: No plan mode
      usePlanModeStore.setState({
        currentPlan: null,
        planModeStatus: {
          is_in_plan_mode: false,
          current_mode: 'build' as const,
          current_plan_id: null,
          plan: null,
        },
        planLoading: false,
        planError: null,
      });

      useAgentV3Store.setState({
        conversations: [],
        activeConversationId: 'conv-123',
        timeline: [],
        messages: [],
        isLoadingHistory: false,
        isStreaming: false,
        workPlan: null,
        executionPlan: null,
        isPlanMode: false,
        showPlanPanel: true,
        pendingDecision: null,
        doomLoopDetected: null,
        error: null,
      });

      await act(async () => {
        renderWithRouter(
          <AgentChat />
        );
      });

      // Assert: EmptyState should be visible
      await waitFor(() => {
        const emptyState = screen.queryByText('No active plan');
        expect(emptyState).toBeInTheDocument();
      });
    });

    it('should display loading spinner while plan is loading', async () => {
      // Setup: Plan is loading
      usePlanModeStore.setState({
        currentPlan: null,
        planModeStatus: {
          is_in_plan_mode: true,
          current_mode: 'plan' as const,
          current_plan_id: null,  // Loading, so no plan yet
          plan: null,
        },
        planLoading: true,
        planError: null,
      });

      useAgentV3Store.setState({
        conversations: [],
        activeConversationId: 'conv-123',
        timeline: [],
        messages: [],
        isLoadingHistory: false,
        isStreaming: false,
        workPlan: null,
        executionPlan: null,
        isPlanMode: true,
        showPlanPanel: true,
        pendingDecision: null,
        doomLoopDetected: null,
        error: null,
      });

      await act(async () => {
        renderWithRouter(
          <AgentChat />
        );
      });

      // Assert: Loading spinner should be visible
      await waitFor(() => {
        const loadingText = screen.queryByText('Loading plan...');
        expect(loadingText).toBeInTheDocument();
      });
    });
  });

  describe('PlanEditor Callbacks', () => {
    it('should call onUpdate when user saves plan changes', async () => {
      const updatePlanSpy = vi.spyOn(usePlanModeStore.getState(), 'updatePlan');

      usePlanModeStore.setState({
        currentPlan: mockPlanDocument,
        planModeStatus: mockPlanModeStatus,
        planLoading: false,
        planError: null,
      });

      useAgentV3Store.setState({
        conversations: [],
        activeConversationId: 'conv-123',
        timeline: [],
        messages: [],
        isLoadingHistory: false,
        isStreaming: false,
        workPlan: null,
        executionPlan: null,
        isPlanMode: true,
        showPlanPanel: true,
        pendingDecision: null,
        doomLoopDetected: null,
        error: null,
      });

      await act(async () => {
        renderWithRouter(
          <AgentChat />
        );
      });

      // Wait for PlanEditor to render
      await waitFor(() => {
        expect(screen.queryByText('Test Plan')).toBeInTheDocument();
      });

      // Find and click Edit button
      const editButtons = screen.queryAllByText('Edit');
      const editButton = editButtons.find(btn => btn.textContent === 'Edit');
      if (editButton) {
        await userEvent.click(editButton);
      }

      // Wait for textareas to appear (there will be multiple)
      await waitFor(() => {
        const textAreas = screen.queryAllByRole('textbox');
        expect(textAreas.length).toBeGreaterThan(0);
      });

      // Find the textarea with monospace font (that's the PlanEditor one)
      const textAreas = screen.queryAllByRole('textbox');
      const planEditorTextArea = textAreas.find(ta =>
        ta.classList.contains('text-slate-900') || ta.classList.contains('font-mono')
      );

      // Modify content if we found the right textarea
      if (planEditorTextArea) {
        await userEvent.clear(planEditorTextArea);
        await userEvent.type(planEditorTextArea, 'Updated plan content');
      }

      // Click Save button
      const saveButton = screen.queryByText('Save');
      if (saveButton) {
        await userEvent.click(saveButton);
      }

      // Assert: updatePlan should have been called
      await waitFor(() => {
        expect(updatePlanSpy).toHaveBeenCalled();
      }, { timeout: 3000 });
    });

    it('should call submitPlanForReview when user submits for review', async () => {
      const submitSpy = vi.spyOn(usePlanModeStore.getState(), 'submitPlanForReview');

      usePlanModeStore.setState({
        currentPlan: mockPlanDocument,
        planModeStatus: mockPlanModeStatus,
        planLoading: false,
        planError: null,
      });

      useAgentV3Store.setState({
        conversations: [],
        activeConversationId: 'conv-123',
        timeline: [],
        messages: [],
        isLoadingHistory: false,
        isStreaming: false,
        workPlan: null,
        executionPlan: null,
        isPlanMode: true,
        showPlanPanel: true,
        pendingDecision: null,
        doomLoopDetected: null,
        error: null,
      });

      await act(async () => {
        renderWithRouter(
          <AgentChat />
        );
      });

      // Wait for PlanEditor to render
      await waitFor(() => {
        expect(screen.queryByText('Test Plan')).toBeInTheDocument();
      });

      // Click Submit for Review button
      const submitButton = screen.queryByText('Submit for Review');
      if (submitButton) {
        await userEvent.click(submitButton);
      }

      // Assert: submitPlanForReview should have been called
      await waitFor(() => {
        expect(submitSpy).toHaveBeenCalledWith('plan-123');
      });
    });

    it('should call exitPlanMode when user approves and exits', async () => {
      const exitSpy = vi.spyOn(usePlanModeStore.getState(), 'exitPlanMode');

      usePlanModeStore.setState({
        currentPlan: mockPlanDocument,
        planModeStatus: mockPlanModeStatus,
        planLoading: false,
        planError: null,
      });

      useAgentV3Store.setState({
        conversations: [],
        activeConversationId: 'conv-123',
        timeline: [],
        messages: [],
        isLoadingHistory: false,
        isStreaming: false,
        workPlan: null,
        executionPlan: null,
        isPlanMode: true,
        showPlanPanel: true,
        pendingDecision: null,
        doomLoopDetected: null,
        error: null,
      });

      await act(async () => {
        renderWithRouter(
          <AgentChat />
        );
      });

      // Wait for PlanEditor to render
      await waitFor(() => {
        expect(screen.queryByText('Test Plan')).toBeInTheDocument();
      });

      // Find and click Approve & Exit button
      const approveButtons = screen.queryAllByText('Approve & Exit');
      expect(approveButtons.length).toBeGreaterThan(0);

      if (approveButtons.length > 0) {
        await userEvent.click(approveButtons[0]);
      }

      // Assert: exitPlanMode should have been called (Modal.confirm mock auto-confirms)
      await waitFor(() => {
        expect(exitSpy).toHaveBeenCalled();
      }, { timeout: 3000 });

      // Verify it was called with correct arguments (conversationId, planId, approve=true)
      expect(exitSpy).toHaveBeenCalledWith('conv-123', 'plan-123', true, undefined);
    });

    it('should call exitPlanMode with approve=false when user exits without approval', async () => {
      const exitSpy = vi.spyOn(usePlanModeStore.getState(), 'exitPlanMode');

      usePlanModeStore.setState({
        currentPlan: mockPlanDocument,
        planModeStatus: mockPlanModeStatus,
        planLoading: false,
        planError: null,
      });

      useAgentV3Store.setState({
        conversations: [],
        activeConversationId: 'conv-123',
        timeline: [],
        messages: [],
        isLoadingHistory: false,
        isStreaming: false,
        workPlan: null,
        executionPlan: null,
        isPlanMode: true,
        showPlanPanel: true,
        pendingDecision: null,
        doomLoopDetected: null,
        error: null,
      });

      await act(async () => {
        renderWithRouter(
          <AgentChat />
        );
      });

      // Wait for PlanEditor to render
      await waitFor(() => {
        expect(screen.queryByText('Test Plan')).toBeInTheDocument();
      });

      // Find and click Exit without Approval button
      const exitButtons = screen.queryAllByText('Exit without Approval');
      expect(exitButtons.length).toBeGreaterThan(0);

      if (exitButtons.length > 0) {
        await userEvent.click(exitButtons[0]);
      }

      // Assert: exitPlanMode should have been called (Modal.confirm mock auto-confirms)
      await waitFor(() => {
        expect(exitSpy).toHaveBeenCalled();
      }, { timeout: 3000 });

      // Verify it was called with correct arguments (conversationId, planId, approve=false)
      expect(exitSpy).toHaveBeenCalledWith('conv-123', 'plan-123', false, undefined);
    });
  });

  describe('Error Handling', () => {
    it('should display error message when plan operations fail', async () => {
      // Setup: Plan error
      usePlanModeStore.setState({
        currentPlan: null,
        planModeStatus: {
          is_in_plan_mode: true,
          current_mode: 'plan' as const,
          current_plan_id: null,
          plan: null,
        },
        planLoading: false,
        planError: 'Failed to load plan',
      });

      useAgentV3Store.setState({
        conversations: [],
        activeConversationId: 'conv-123',
        timeline: [],
        messages: [],
        isLoadingHistory: false,
        isStreaming: false,
        workPlan: null,
        executionPlan: null,
        isPlanMode: true,
        showPlanPanel: true,
        pendingDecision: null,
        doomLoopDetected: null,
        error: null,
      });

      await act(async () => {
        renderWithRouter(
          <AgentChat />
        );
      });

      // Assert: Error should be visible (check for Alert component)
      await waitFor(() => {
        // Check for the Alert title
        const errorTitle = screen.queryByText('Plan Mode Error');
        expect(errorTitle).toBeInTheDocument();

        // Also check for the error description
        const errorDescription = screen.queryByText('Failed to load plan');
        expect(errorDescription).toBeInTheDocument();
      });
    });
  });
});

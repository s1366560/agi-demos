/**
 * Unit tests for executionStore.
 *
 * TDD RED Phase: Tests written first for Execution store split.
 *
 * Feature: Split Execution state from monolithic agent store.
 *
 * Execution state includes:
 * - currentWorkPlan: Current WorkPlan being executed
 * - currentStepNumber: Currently executing step number
 * - currentStepStatus: Status of current step (pending/running/completed/failed)
 * - executionTimeline: Timeline of steps being executed
 * - currentToolExecution: Currently running tool execution
 * - toolExecutionHistory: History of all tool executions
 * - matchedPattern: Pattern match result (T079)
 *
 * Actions:
 * - setWorkPlan: Set work plan and build execution timeline
 * - startStep: Start executing a step
 * - completeStep: Complete a step with success/failure
 * - addThought: Add thought to a step
 * - startTool: Start a tool execution
 * - completeTool: Complete a tool execution with result
 * - clearExecution: Clear all execution state
 * - reset: Reset to initial state
 *
 * These tests verify that the executionStore maintains the same behavior
 * as the original monolithic agent store's execution functionality.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useExecutionStore, initialState } from '../../../stores/agent/executionStore';
import type { WorkPlan } from '../../../types/agent';

describe('ExecutionStore', () => {
    beforeEach(() => {
        // Reset store before each test
        useExecutionStore.getState().reset();
        vi.clearAllMocks();
    });

    describe('Initial State', () => {
        it('should have correct initial state', () => {
            const state = useExecutionStore.getState();
            expect(state.currentWorkPlan).toBe(initialState.currentWorkPlan);
            expect(state.currentStepNumber).toBe(initialState.currentStepNumber);
            expect(state.currentStepStatus).toBe(initialState.currentStepStatus);
            expect(state.executionTimeline).toEqual(initialState.executionTimeline);
            expect(state.currentToolExecution).toBe(initialState.currentToolExecution);
            expect(state.toolExecutionHistory).toEqual(initialState.toolExecutionHistory);
            expect(state.matchedPattern).toBe(initialState.matchedPattern);
        });

        it('should have null work plan initially', () => {
            const { currentWorkPlan } = useExecutionStore.getState();
            expect(currentWorkPlan).toBe(null);
        });

        it('should have null step number initially', () => {
            const { currentStepNumber } = useExecutionStore.getState();
            expect(currentStepNumber).toBe(null);
        });

        it('should have null step status initially', () => {
            const { currentStepStatus } = useExecutionStore.getState();
            expect(currentStepStatus).toBe(null);
        });

        it('should have empty execution timeline initially', () => {
            const { executionTimeline } = useExecutionStore.getState();
            expect(executionTimeline).toEqual([]);
        });

        it('should have null current tool execution initially', () => {
            const { currentToolExecution } = useExecutionStore.getState();
            expect(currentToolExecution).toBe(null);
        });

        it('should have empty tool execution history initially', () => {
            const { toolExecutionHistory } = useExecutionStore.getState();
            expect(toolExecutionHistory).toEqual([]);
        });

        it('should have null matched pattern initially', () => {
            const { matchedPattern } = useExecutionStore.getState();
            expect(matchedPattern).toBe(null);
        });
    });

    describe('reset', () => {
        it('should reset state to initial values', () => {
            // Set some state
            const workPlan: WorkPlan = {
                id: 'plan-1',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'Step 1',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.setState({
                currentWorkPlan: workPlan,
                currentStepNumber: 1,
                currentStepStatus: 'running',
                executionTimeline: [
                    {
                        stepNumber: 1,
                        description: 'Step 1',
                        status: 'running',
                        thoughts: [],
                        toolExecutions: [],
                    },
                ],
                currentToolExecution: {
                    id: 'tool-1',
                    toolName: 'test_tool',
                    input: {},
                    startTime: new Date().toISOString(),
                },
                toolExecutionHistory: [
                    {
                        id: 'tool-1',
                        toolName: 'test_tool',
                        input: {},
                        status: 'running',
                        startTime: new Date().toISOString(),
                    },
                ],
                matchedPattern: { id: 'pattern-1', similarity: 0.9, query: 'test' },
            });

            // Verify state is set
            expect(useExecutionStore.getState().currentWorkPlan).toEqual(workPlan);
            expect(useExecutionStore.getState().currentStepNumber).toBe(1);

            // Reset
            useExecutionStore.getState().reset();

            // Verify initial state restored
            const state = useExecutionStore.getState();
            expect(state.currentWorkPlan).toBe(null);
            expect(state.currentStepNumber).toBe(null);
            expect(state.currentStepStatus).toBe(null);
            expect(state.executionTimeline).toEqual([]);
            expect(state.currentToolExecution).toBe(null);
            expect(state.toolExecutionHistory).toEqual([]);
            expect(state.matchedPattern).toBe(null);
        });
    });

    describe('setWorkPlan', () => {
        it('should set work plan and build execution timeline', () => {
            const workPlan: WorkPlan = {
                id: 'plan-1',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'Search for information',
                        thought_prompt: '',
                        required_tools: ['web_search'],
                        expected_output: 'Search results',
                        dependencies: [],
                    },
                    {
                        step_number: 2,
                        description: 'Analyze results',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: 'Analysis',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(workPlan);

            const { currentWorkPlan, executionTimeline, toolExecutionHistory } =
                useExecutionStore.getState();

            expect(currentWorkPlan).toEqual(workPlan);
            expect(executionTimeline).toHaveLength(2);
            expect(executionTimeline[0]).toEqual({
                stepNumber: 1,
                description: 'Search for information',
                status: 'pending',
                thoughts: [],
                toolExecutions: [],
            });
            expect(executionTimeline[1]).toEqual({
                stepNumber: 2,
                description: 'Analyze results',
                status: 'pending',
                thoughts: [],
                toolExecutions: [],
            });
            expect(toolExecutionHistory).toEqual([]);
        });

        it('should clear tool execution history when setting new work plan', () => {
            // Set existing tool executions
            useExecutionStore.setState({
                toolExecutionHistory: [
                    {
                        id: 'old-tool',
                        toolName: 'old_tool',
                        input: {},
                        status: 'success',
                        startTime: new Date().toISOString(),
                        result: 'old result',
                    },
                ],
            });

            const workPlan: WorkPlan = {
                id: 'plan-1',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'Step 1',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(workPlan);

            expect(useExecutionStore.getState().toolExecutionHistory).toEqual([]);
        });

        it('should replace existing work plan and timeline', () => {
            // Set existing work plan
            const oldPlan: WorkPlan = {
                id: 'plan-old',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'Old Step',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(oldPlan);
            expect(useExecutionStore.getState().executionTimeline).toHaveLength(1);

            // Set new work plan
            const newPlan: WorkPlan = {
                id: 'plan-new',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'New Step 1',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                    {
                        step_number: 2,
                        description: 'New Step 2',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(newPlan);

            expect(useExecutionStore.getState().currentWorkPlan?.id).toBe('plan-new');
            expect(useExecutionStore.getState().executionTimeline).toHaveLength(2);
        });
    });

    describe('startStep', () => {
        it('should update step status to running', () => {
            // Set up work plan first
            const workPlan: WorkPlan = {
                id: 'plan-1',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'Step 1',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(workPlan);

            // Start step
            useExecutionStore.getState().startStep(1, 'Executing step 1');

            const { currentStepNumber, currentStepStatus, executionTimeline } =
                useExecutionStore.getState();

            expect(currentStepNumber).toBe(1);
            expect(currentStepStatus).toBe('running');
            expect(executionTimeline[0].status).toBe('running');
            expect(executionTimeline[0].startTime).toBeDefined();
        });

        it('should handle step that does not exist in timeline', () => {
            const workPlan: WorkPlan = {
                id: 'plan-1',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'Step 1',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(workPlan);

            // Try to start non-existent step
            useExecutionStore.getState().startStep(99, 'Executing step 99');

            const { currentStepNumber, currentStepStatus, executionTimeline } =
                useExecutionStore.getState();

            expect(currentStepNumber).toBe(99);
            expect(currentStepStatus).toBe('running');
            // Timeline should be unchanged (step 99 doesn't exist)
            expect(executionTimeline[0].stepNumber).toBe(1);
            expect(executionTimeline[0].status).toBe('pending');
        });
    });

    describe('completeStep', () => {
        it('should update step status to completed on success', () => {
            const workPlan: WorkPlan = {
                id: 'plan-1',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'Step 1',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(workPlan);
            useExecutionStore.getState().startStep(1, 'Executing step 1');

            // Complete step successfully
            useExecutionStore.getState().completeStep(1, true, 0);

            const { currentStepStatus, executionTimeline } = useExecutionStore.getState();

            expect(currentStepStatus).toBe('completed');
            expect(executionTimeline[0].status).toBe('completed');
            expect(executionTimeline[0].endTime).toBeDefined();
            expect(executionTimeline[0].duration).toBeDefined();
        });

        it('should update step status to failed on failure', () => {
            const workPlan: WorkPlan = {
                id: 'plan-1',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'Step 1',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(workPlan);
            useExecutionStore.getState().startStep(1, 'Executing step 1');

            // Complete step with failure
            useExecutionStore.getState().completeStep(1, false, 0);

            const { currentStepStatus, executionTimeline } = useExecutionStore.getState();

            expect(currentStepStatus).toBe('failed');
            expect(executionTimeline[0].status).toBe('failed');
            expect(executionTimeline[0].endTime).toBeDefined();
        });

        it('should update work plan current_step_index', () => {
            const workPlan: WorkPlan = {
                id: 'plan-1',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'Step 1',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                    {
                        step_number: 2,
                        description: 'Step 2',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(workPlan);
            expect(useExecutionStore.getState().currentWorkPlan?.current_step_index).toBe(0);

            useExecutionStore.getState().completeStep(1, true, 1);

            expect(useExecutionStore.getState().currentWorkPlan?.current_step_index).toBe(1);
        });

        it('should mark running tool executions as complete/failed', () => {
            const workPlan: WorkPlan = {
                id: 'plan-1',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'Step 1',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(workPlan);
            useExecutionStore.getState().startStep(1, 'Executing step 1');

            // Start a tool execution
            useExecutionStore.getState().startTool('test_tool', {}, 1, 'tool-1');

            // Complete step with failure
            useExecutionStore.getState().completeStep(1, false, 0);

            const { executionTimeline } = useExecutionStore.getState();
            const toolExecution = executionTimeline[0].toolExecutions[0];

            expect(toolExecution.status).toBe('failed');
            expect(toolExecution.endTime).toBeDefined();
        });
    });

    describe('addThought', () => {
        it('should add thought to current step', () => {
            const workPlan: WorkPlan = {
                id: 'plan-1',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'Step 1',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(workPlan);
            useExecutionStore.getState().startStep(1, 'Executing step 1');

            useExecutionStore.getState().addThought('This is a thought', 1);

            const { executionTimeline } = useExecutionStore.getState();

            expect(executionTimeline[0].thoughts).toEqual(['This is a thought']);
        });

        it('should add multiple thoughts to step', () => {
            const workPlan: WorkPlan = {
                id: 'plan-1',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'Step 1',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(workPlan);

            useExecutionStore.getState().addThought('First thought', 1);
            useExecutionStore.getState().addThought('Second thought', 1);
            useExecutionStore.getState().addThought('Third thought', 1);

            const { executionTimeline } = useExecutionStore.getState();

            expect(executionTimeline[0].thoughts).toEqual([
                'First thought',
                'Second thought',
                'Third thought',
            ]);
        });

        it('should use current step number if not provided', () => {
            const workPlan: WorkPlan = {
                id: 'plan-1',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'Step 1',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(workPlan);
            useExecutionStore.getState().startStep(1, 'Executing step 1');

            useExecutionStore.getState().addThought('Thought without step number');

            const { executionTimeline } = useExecutionStore.getState();

            expect(executionTimeline[0].thoughts).toEqual(['Thought without step number']);
        });

        it('should handle thought when no step is active', () => {
            const workPlan: WorkPlan = {
                id: 'plan-1',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'Step 1',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(workPlan);
            // Don't start a step

            useExecutionStore.getState().addThought('Thought with no active step');

            // Should not crash, timeline should remain unchanged
            const { executionTimeline } = useExecutionStore.getState();
            expect(executionTimeline[0].thoughts).toEqual([]);
        });
    });

    describe('startTool', () => {
        it('should create new tool execution', () => {
            const startTime = new Date().toISOString();

            useExecutionStore.getState().startTool('web_search', { query: 'test' }, 1, 'tool-1', startTime);

            const { currentToolExecution, toolExecutionHistory } = useExecutionStore.getState();

            expect(currentToolExecution).toEqual({
                id: 'tool-1',
                toolName: 'web_search',
                input: { query: 'test' },
                startTime,
                stepNumber: 1,
            });

            expect(toolExecutionHistory).toHaveLength(1);
            expect(toolExecutionHistory[0]).toEqual({
                id: 'tool-1',
                toolName: 'web_search',
                input: { query: 'test' },
                status: 'running',
                startTime,
                stepNumber: 1,
            });
        });

        it('should add tool execution to timeline step', () => {
            const workPlan: WorkPlan = {
                id: 'plan-1',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'Step 1',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(workPlan);
            useExecutionStore.getState().startStep(1, 'Executing step 1');

            useExecutionStore.getState().startTool('web_search', { query: 'test' }, 1, 'tool-1');

            const { executionTimeline } = useExecutionStore.getState();

            expect(executionTimeline[0].toolExecutions).toHaveLength(1);
            expect(executionTimeline[0].toolExecutions[0]).toEqual({
                id: 'tool-1',
                toolName: 'web_search',
                input: { query: 'test' },
                status: 'running',
                startTime: expect.any(String),
                stepNumber: 1,
            });
        });

        it('should use current step number if not provided', () => {
            const workPlan: WorkPlan = {
                id: 'plan-1',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'Step 1',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(workPlan);
            useExecutionStore.getState().startStep(1, 'Executing step 1');

            useExecutionStore.getState().startTool('web_search', { query: 'test' });

            const { executionTimeline } = useExecutionStore.getState();

            expect(executionTimeline[0].toolExecutions[0].stepNumber).toBe(1);
        });

        it('should handle tool execution without step number', () => {
            useExecutionStore.getState().startTool('web_search', { query: 'test' });

            const { toolExecutionHistory } = useExecutionStore.getState();

            expect(toolExecutionHistory[0].stepNumber).toBeUndefined();
            expect(toolExecutionHistory).toHaveLength(1);
        });
    });

    describe('completeTool', () => {
        beforeEach(() => {
            // Set up work plan and start a tool
            const workPlan: WorkPlan = {
                id: 'plan-1',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'Step 1',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(workPlan);
            useExecutionStore.getState().startStep(1, 'Executing step 1');
            useExecutionStore.getState().startTool('web_search', { query: 'test' }, 1, 'tool-1');
        });

        it('should complete tool with success result', () => {
            const observation = 'Search completed successfully';
            const callId = 'tool-1';

            useExecutionStore.getState().completeTool(callId, observation);

            const { toolExecutionHistory, executionTimeline } = useExecutionStore.getState();

            expect(toolExecutionHistory[0].status).toBe('success');
            expect(toolExecutionHistory[0].result).toBe(observation);
            expect(toolExecutionHistory[0].endTime).toBeDefined();
            expect(toolExecutionHistory[0].duration).toBeDefined();

            expect(executionTimeline[0].toolExecutions[0].status).toBe('success');
            expect(executionTimeline[0].toolExecutions[0].result).toBe(observation);
        });

        it('should complete tool with error', () => {
            const observation = 'Error: Search failed';
            const callId = 'tool-1';

            // Pass isError=true explicitly since we now require explicit error flag
            useExecutionStore.getState().completeTool(callId, observation, true);

            const { toolExecutionHistory, executionTimeline } = useExecutionStore.getState();

            expect(toolExecutionHistory[0].status).toBe('failed');
            expect(toolExecutionHistory[0].error).toBe(observation);
            expect(toolExecutionHistory[0].result).toBeUndefined();

            expect(executionTimeline[0].toolExecutions[0].status).toBe('failed');
            expect(executionTimeline[0].toolExecutions[0].error).toBe(observation);
        });

        it('should fall back to current tool execution if callId not provided', () => {
            const observation = 'Search completed successfully';

            useExecutionStore.getState().completeTool(undefined, observation);

            const { currentToolExecution, toolExecutionHistory } = useExecutionStore.getState();

            expect(currentToolExecution).not.toBe(null);
            expect(toolExecutionHistory[0].status).toBe('success');
            expect(toolExecutionHistory[0].result).toBe(observation);
        });

        it('should clear current tool execution after completion', () => {
            expect(useExecutionStore.getState().currentToolExecution).not.toBe(null);

            useExecutionStore.getState().completeTool('tool-1', 'Result');

            expect(useExecutionStore.getState().currentToolExecution).toBe(null);
        });

        it('should handle tool not found in history', () => {
            // This should not crash
            useExecutionStore.getState().completeTool('non-existent-tool', 'Result');

            const { toolExecutionHistory } = useExecutionStore.getState();

            // Original tool should still be there
            expect(toolExecutionHistory).toHaveLength(1);
        });
    });

    describe('clearExecution', () => {
        it('should clear all execution state', () => {
            const workPlan: WorkPlan = {
                id: 'plan-1',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'Step 1',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(workPlan);
            useExecutionStore.getState().startStep(1, 'Executing step 1');
            useExecutionStore.getState().startTool('web_search', { query: 'test' }, 1, 'tool-1');
            useExecutionStore.getState().setMatchedPattern({
                id: 'pattern-1',
                similarity: 0.9,
                query: 'test',
            });

            expect(useExecutionStore.getState().currentWorkPlan).not.toBe(null);
            expect(useExecutionStore.getState().executionTimeline).toHaveLength(1);

            useExecutionStore.getState().clearExecution();

            expect(useExecutionStore.getState().currentWorkPlan).toBe(null);
            expect(useExecutionStore.getState().currentStepNumber).toBe(null);
            expect(useExecutionStore.getState().currentStepStatus).toBe(null);
            expect(useExecutionStore.getState().executionTimeline).toEqual([]);
            expect(useExecutionStore.getState().currentToolExecution).toBe(null);
            expect(useExecutionStore.getState().toolExecutionHistory).toEqual([]);
            expect(useExecutionStore.getState().matchedPattern).toBe(null);
        });
    });

    describe('setMatchedPattern', () => {
        it('should set matched pattern', () => {
            const pattern = {
                id: 'pattern-1',
                similarity: 0.95,
                query: 'test query',
            };

            useExecutionStore.getState().setMatchedPattern(pattern);

            expect(useExecutionStore.getState().matchedPattern).toEqual(pattern);
        });

        it('should clear matched pattern when set to null', () => {
            useExecutionStore.getState().setMatchedPattern({
                id: 'pattern-1',
                similarity: 0.95,
                query: 'test query',
            });

            useExecutionStore.getState().setMatchedPattern(null);

            expect(useExecutionStore.getState().matchedPattern).toBe(null);
        });
    });

    describe('Edge Cases', () => {
        it('should handle rapid tool start/complete cycles', () => {
            // Start tool 1
            useExecutionStore.getState().startTool('tool1', {}, 1, 'tool-1');
            expect(useExecutionStore.getState().toolExecutionHistory).toHaveLength(1);

            // Complete tool 1
            useExecutionStore.getState().completeTool('tool-1', 'Result 1');
            expect(useExecutionStore.getState().toolExecutionHistory[0].status).toBe('success');

            // Start tool 2
            useExecutionStore.getState().startTool('tool2', {}, 1, 'tool-2');
            expect(useExecutionStore.getState().toolExecutionHistory).toHaveLength(2);

            // Complete tool 2
            useExecutionStore.getState().completeTool('tool-2', 'Result 2');
            expect(useExecutionStore.getState().toolExecutionHistory[1].status).toBe('success');
        });

        it('should handle multiple steps execution', () => {
            const workPlan: WorkPlan = {
                id: 'plan-1',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'Step 1',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                    {
                        step_number: 2,
                        description: 'Step 2',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(workPlan);

            // Execute step 1
            useExecutionStore.getState().startStep(1, 'Executing step 1');
            useExecutionStore.getState().addThought('Thought for step 1', 1);
            useExecutionStore.getState().completeStep(1, true, 1);

            // Execute step 2
            useExecutionStore.getState().startStep(2, 'Executing step 2');
            useExecutionStore.getState().addThought('Thought for step 2', 2);
            useExecutionStore.getState().completeStep(2, true, 2);

            const { executionTimeline } = useExecutionStore.getState();

            expect(executionTimeline[0].status).toBe('completed');
            expect(executionTimeline[0].thoughts).toHaveLength(1);
            expect(executionTimeline[1].status).toBe('completed');
            expect(executionTimeline[1].thoughts).toHaveLength(1);
        });

        it('should handle empty work plan steps', () => {
            const workPlan: WorkPlan = {
                id: 'plan-1',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(workPlan);

            expect(useExecutionStore.getState().executionTimeline).toEqual([]);
        });

        it('should handle tool execution with no step number when timeline has steps', () => {
            const workPlan: WorkPlan = {
                id: 'plan-1',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'Step 1',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(workPlan);
            useExecutionStore.getState().startTool('web_search', { query: 'test' }, undefined, 'tool-1');

            const { executionTimeline, toolExecutionHistory } = useExecutionStore.getState();

            // Tool should be in history but not in timeline step
            expect(toolExecutionHistory).toHaveLength(1);
            expect(executionTimeline[0].toolExecutions).toHaveLength(0);
        });
    });

    describe('State Immutability', () => {
        it('should reset properly after multiple state changes', () => {
            const workPlan: WorkPlan = {
                id: 'plan-1',
                conversation_id: 'conv-1',
                status: 'in_progress',
                steps: [
                    {
                        step_number: 1,
                        description: 'Step 1',
                        thought_prompt: '',
                        required_tools: [],
                        expected_output: '',
                        dependencies: [],
                    },
                ],
                current_step_index: 0,
                created_at: new Date().toISOString(),
            };

            useExecutionStore.getState().setWorkPlan(workPlan);
            useExecutionStore.getState().startStep(1, 'Executing step 1');
            useExecutionStore.getState().startTool('web_search', { query: 'test' }, 1, 'tool-1');
            useExecutionStore.getState().setMatchedPattern({
                id: 'pattern-1',
                similarity: 0.9,
                query: 'test',
            });

            // Reset
            useExecutionStore.getState().reset();

            // Verify all state reset
            const state = useExecutionStore.getState();
            expect(state.currentWorkPlan).toBe(null);
            expect(state.currentStepNumber).toBe(null);
            expect(state.currentStepStatus).toBe(null);
            expect(state.executionTimeline).toEqual([]);
            expect(state.currentToolExecution).toBe(null);
            expect(state.toolExecutionHistory).toEqual([]);
            expect(state.matchedPattern).toBe(null);
        });
    });
});

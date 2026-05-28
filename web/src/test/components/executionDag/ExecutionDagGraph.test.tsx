import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ExecutionDagGraph } from '@/components/executionDag/ExecutionDagGraph';
import { fireEvent, render, screen } from '@/test/utils';

import type { ExecutionDagModel } from '@/components/executionDag/types';

const model: ExecutionDagModel = {
  rootId: 'root',
  nodes: [
    {
      id: 'root',
      title: 'Root goal',
      kind: 'root',
      status: 'active',
      selectable: false,
    },
    {
      id: 'task-1',
      title: 'Implement graph',
      kind: 'task',
      status: 'in_progress',
      execution: 'running',
      agentLabel: 'Worker A',
      attemptId: 'attempt-1',
      progress: 50,
      metrics: { evidence: 2, artifacts: 1 },
    },
  ],
  edges: [{ id: 'hierarchy:root:task-1', sourceId: 'root', targetId: 'task-1', kind: 'hierarchy' }],
};

describe('ExecutionDagGraph', () => {
  beforeEach(() => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      value: vi.fn(),
    });
  });

  it('renders an empty state when no model is available', () => {
    render(<ExecutionDagGraph model={null} />);

    expect(screen.getByTestId('execution-dag-empty')).toBeInTheDocument();
  });

  it('renders nodes and edges with stable SVG semantics', () => {
    render(<ExecutionDagGraph model={model} selectedNodeId="task-1" />);

    expect(screen.getByTestId('execution-dag-graph')).toBeInTheDocument();
    expect(screen.getByTestId('execution-dag-node-task-1')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('Implement graph')).toBeInTheDocument();
    expect(screen.getByText('Worker A')).toBeInTheDocument();
  });

  it('can fit the graph SVG to the available panel width', () => {
    render(<ExecutionDagGraph model={model} fitToWidth />);

    const graph = screen.getByTestId('execution-dag-graph');
    expect(graph).toHaveAttribute('data-fit-to-width', 'true');
    expect(screen.getByTestId('execution-dag-svg')).toHaveClass('w-full');
  });

  it('renders graph interaction tools and an overview map', () => {
    render(<ExecutionDagGraph model={model} selectedNodeId="task-1" fitToWidth />);

    expect(screen.getByLabelText('Graph tools')).toBeInTheDocument();
    expect(screen.getByLabelText('Zoom out')).toBeInTheDocument();
    expect(screen.getByLabelText('Zoom level')).toBeInTheDocument();
    expect(screen.getByLabelText('Zoom in')).toBeInTheDocument();
    expect(screen.getByLabelText('Fit width')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('Actual size')).toBeInTheDocument();
    expect(screen.getByLabelText('Reset view')).toBeInTheDocument();
    expect(screen.getByLabelText('Drag to pan')).toBeInTheDocument();
    expect(screen.getByLabelText('Center selected node')).toBeEnabled();
    expect(screen.getByLabelText('Center current or root node')).toBeInTheDocument();
    expect(screen.getByLabelText('Toggle overview map')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('Download SVG')).toBeInTheDocument();
    const overviewOverlay = screen.getByTestId('execution-dag-minimap-overlay');
    expect(overviewOverlay).toContainElement(screen.getByTestId('execution-dag-minimap'));
    expect(screen.getByTestId('execution-dag-graph')).toContainElement(overviewOverlay);
    expect(screen.getByTestId('execution-dag-canvas')).not.toContainElement(overviewOverlay);
  });

  it('supports zoom, pan mode, overview toggle, and keyboard shortcuts', () => {
    render(<ExecutionDagGraph model={model} fitToWidth />);

    const graph = screen.getByTestId('execution-dag-graph');
    fireEvent.click(screen.getByLabelText('Zoom in'));
    expect(graph).not.toHaveAttribute('data-fit-to-width');

    fireEvent.click(screen.getByLabelText('Fit width'));
    expect(graph).toHaveAttribute('data-fit-to-width', 'true');

    fireEvent.click(screen.getByLabelText('Drag to pan'));
    expect(screen.getByLabelText('Drag to pan')).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(screen.getByLabelText('Toggle overview map'));
    expect(screen.queryByTestId('execution-dag-minimap')).not.toBeInTheDocument();

    fireEvent.keyDown(graph, { key: '-' });
    expect(graph).not.toHaveAttribute('data-fit-to-width');
  });

  it('supports click and keyboard node selection', () => {
    const onNodeSelect = vi.fn();
    render(<ExecutionDagGraph model={model} onNodeSelect={onNodeSelect} />);

    const taskNode = screen.getByTestId('execution-dag-node-task-1');
    fireEvent.click(taskNode);
    fireEvent.keyDown(taskNode, { key: 'Enter' });

    expect(onNodeSelect).toHaveBeenCalledWith('task-1');
    expect(onNodeSelect).toHaveBeenCalledTimes(2);
  });

  it('dims nonmatching nodes without hiding them', () => {
    render(<ExecutionDagGraph model={model} dimmedNodeIds={new Set(['task-1'])} />);

    expect(screen.getByTestId('execution-dag-node-task-1')).toHaveClass('opacity-35');
    expect(screen.getByText('Implement graph')).toBeInTheDocument();
  });

  it('marks the current session node independently from selection', () => {
    render(<ExecutionDagGraph model={model} highlightedNodeId="task-1" />);

    expect(screen.getByTestId('execution-dag-node-task-1')).toHaveAttribute(
      'data-current-session-node',
      'true'
    );
    expect(screen.getByText('Current session')).toBeInTheDocument();
  });

  it('centers the current session node inside the scroll container', () => {
    const scrollTo = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      value: scrollTo,
    });

    render(<ExecutionDagGraph model={model} highlightedNodeId="task-1" />);

    expect(scrollTo).toHaveBeenCalledWith(
      expect.objectContaining({
        behavior: 'auto',
        left: expect.any(Number),
        top: expect.any(Number),
      })
    );
    expect(scrollTo.mock.calls[0]?.[0]).toMatchObject({
      left: expect.any(Number),
      top: expect.any(Number),
    });
  });
});

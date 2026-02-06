/**
 * Cytoscape Mock for Testing
 */

import { vi } from 'vitest';

const mockElements = {
  remove: vi.fn(),
  add: vi.fn(),
  length: 0,
};

const mockCytoscapeInstance = {
  on: vi.fn(),
  // Both cyRef.current.elements() and cyRef.current.add need to work
  elements: vi.fn(() => mockElements),
  add: vi.fn(),
  remove: vi.fn(),
  style: vi.fn(),
  layout: vi.fn(() => ({ run: vi.fn() })),
  fit: vi.fn(),
  png: vi.fn(() => 'data:image/png;base64,mock'),
  destroy: vi.fn(),
  boxSelectionEnabled: vi.fn(),
  $: vi.fn(() => ({ unselect: vi.fn() })),
  ready: vi.fn((cb: any) => cb?.()),
  minZoom: 0.1,
  maxZoom: 3,
  wheelSensitivity: 0.2,
};

export const cytoscapeMock = vi.fn(() => mockCytoscapeInstance);

// Mock the module
vi.mock('cytoscape', async () => {
  return {
    default: cytoscapeMock,
    cytoscape: cytoscapeMock,
  };
});

export { mockCytoscapeInstance, mockElements };

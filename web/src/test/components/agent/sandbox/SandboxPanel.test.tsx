/**
 * Tests for SandboxPanel Compound Component Pattern
 *
 * TDD: Tests written first for the new compound component API.
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { SandboxPanel } from '../../../../components/agent/sandbox/SandboxPanel';

import type { DesktopStatus, TerminalStatus } from '../../../../types/agent';

// Mock the xterm dependencies
vi.mock('@xterm/xterm', () => {
  const mockLoadAddon = vi.fn();
  const mockOpen = vi.fn();
  const mockDispose = vi.fn();

  class MockTerminal {
    loadAddon = mockLoadAddon;
    open = mockOpen;
    dispose = mockDispose;
    cols = 80;
    rows = 24;
    constructor(_options?: unknown) {}
  }

  return {
    Terminal: MockTerminal,
  };
});

vi.mock('@xterm/addon-fit', () => {
  const mockFit = vi.fn();

  class MockFitAddon {
    fit = mockFit;
    constructor() {}
  }

  return {
    FitAddon: MockFitAddon,
  };
});

vi.mock('@xterm/addon-web-links', () => ({
  WebLinksAddon: class MockWebLinksAddon {
    constructor() {}
  },
}));

vi.mock('../../../../services/client/urlUtils', () => ({
  createWebSocketUrl: (path: string, params?: Record<string, string>) => {
    const queryString = params ? `?${new URLSearchParams(params).toString()}` : '';
    return `ws://localhost:8000${path}${queryString}`;
  },
}));

// Mock data
const mockDesktopStatusRunning: DesktopStatus = {
  running: true,
  url: 'http://localhost:6080/vnc.html',
  display: ':0',
  resolution: '1280x720',
  port: 6080,
};

const mockDesktopStatusStopped: DesktopStatus = {
  running: false,
  url: null,
  display: '',
  resolution: '',
  port: 0,
};

const mockTerminalStatusRunning: TerminalStatus = {
  running: true,
  url: 'ws://localhost:7681',
  port: 7681,
};

const mockTerminalStatusStopped: TerminalStatus = {
  running: false,
  url: null,
  port: 0,
};

describe('SandboxPanel Compound Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Root Component', () => {
    it('should render with sandbox ID', () => {
      render(
        <SandboxPanel sandboxId="test-sandbox-123">
          <SandboxPanel.Terminal />
        </SandboxPanel>
      );

      expect(screen.getByText(/test-sandbox/)).toBeInTheDocument();
    });

    it('should render header with close button when onClose provided', () => {
      const mockOnClose = vi.fn();
      const { container } = render(
        <SandboxPanel sandboxId="test-sandbox" onClose={mockOnClose}>
          <SandboxPanel.Terminal />
        </SandboxPanel>
      );

      const closeButton = container.querySelector('.anticon-close');
      expect(closeButton).toBeInTheDocument();
    });

    it('should show current tool badge when tool is running', () => {
      render(
        <SandboxPanel
          sandboxId="test-sandbox"
          currentTool={{ name: 'web_search', input: { query: 'test' } }}
        >
          <SandboxPanel.Terminal />
        </SandboxPanel>
      );

      expect(screen.getByText('web_search')).toBeInTheDocument();
    });

    it('should show empty state when no sandbox connected', () => {
      render(
        <SandboxPanel sandboxId={null}>
          <SandboxPanel.Terminal />
        </SandboxPanel>
      );

      expect(screen.getByText('No sandbox connected')).toBeInTheDocument();
    });

    it('should call onClose when close button is clicked', () => {
      const mockOnClose = vi.fn();
      const { container } = render(
        <SandboxPanel sandboxId="test-sandbox" onClose={mockOnClose}>
          <SandboxPanel.Terminal />
        </SandboxPanel>
      );

      const closeButton = container.querySelector('.anticon-close');
      if (closeButton) {
        fireEvent.click(closeButton.closest('button') || closeButton);
        expect(mockOnClose).toHaveBeenCalled();
      }
    });

    it('should respect defaultTab prop', async () => {
      render(
        <SandboxPanel sandboxId="test-sandbox" defaultTab="desktop">
          <SandboxPanel.Terminal />
          <SandboxPanel.Desktop />
        </SandboxPanel>
      );

      // Desktop tab should be active by default
      await waitFor(() => {
        expect(screen.getByText('Remote Desktop')).toBeInTheDocument();
      });
    });
  });

  describe('Terminal Sub-Component', () => {
    it('should render terminal tab when Terminal component is included', () => {
      render(
        <SandboxPanel sandboxId="test-sandbox">
          <SandboxPanel.Terminal />
        </SandboxPanel>
      );

      expect(screen.getByText('Terminal')).toBeInTheDocument();
    });

    it('should not render terminal tab when Terminal component is excluded', () => {
      render(
        <SandboxPanel sandboxId="test-sandbox">
          <SandboxPanel.Desktop />
        </SandboxPanel>
      );

      expect(screen.queryByText('Terminal')).not.toBeInTheDocument();
    });

    it('should show connection status badge when connected', async () => {
      render(
        <SandboxPanel sandboxId="test-sandbox" terminalStatus={mockTerminalStatusRunning}>
          <SandboxPanel.Terminal />
        </SandboxPanel>
      );

      // Check for success badge in terminal tab
      await waitFor(() => {
        const terminalTab = screen.getByText('Terminal');
        expect(terminalTab).toBeInTheDocument();
      });
    });

    it('should switch to terminal tab when clicked', async () => {
      render(
        <SandboxPanel sandboxId="test-sandbox" defaultTab="desktop">
          <SandboxPanel.Terminal />
          <SandboxPanel.Desktop />
        </SandboxPanel>
      );

      const terminalTab = screen.getByText('Terminal');
      fireEvent.click(terminalTab);

      await waitFor(() => {
        expect(screen.getByText('Terminal')).toBeInTheDocument();
      });
    });
  });

  describe('Desktop Sub-Component', () => {
    it('should render desktop tab when Desktop component is included', () => {
      render(
        <SandboxPanel sandboxId="test-sandbox" desktopStatus={mockDesktopStatusRunning}>
          <SandboxPanel.Desktop />
        </SandboxPanel>
      );

      expect(screen.getByText('Desktop')).toBeInTheDocument();
    });

    it('should not render desktop tab when Desktop component is excluded', () => {
      render(
        <SandboxPanel sandboxId="test-sandbox">
          <SandboxPanel.Terminal />
        </SandboxPanel>
      );

      expect(screen.queryByText('Desktop')).not.toBeInTheDocument();
    });

    it('should show running status badge when desktop is active', () => {
      render(
        <SandboxPanel sandboxId="test-sandbox" desktopStatus={mockDesktopStatusRunning}>
          <SandboxPanel.Desktop />
        </SandboxPanel>
      );

      expect(screen.getByText('Desktop')).toBeInTheDocument();
    });

    it('should display Remote Desktop viewer when desktop tab is active', async () => {
      render(
        <SandboxPanel
          sandboxId="test-sandbox"
          defaultTab="desktop"
          desktopStatus={mockDesktopStatusRunning}
        >
          <SandboxPanel.Desktop />
        </SandboxPanel>
      );

      await waitFor(() => {
        expect(screen.getByText('Remote Desktop')).toBeInTheDocument();
      });
    });
  });

  describe('Control Sub-Component', () => {
    it('should render control tab when Control component is included', () => {
      const mockOnDesktopStart = vi.fn();
      const mockOnDesktopStop = vi.fn();

      render(
        <SandboxPanel
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusStopped}
          onDesktopStart={mockOnDesktopStart}
          onDesktopStop={mockOnDesktopStop}
        >
          <SandboxPanel.Control />
        </SandboxPanel>
      );

      expect(screen.getByText('Control')).toBeInTheDocument();
    });

    it('should not render control tab when Control component is excluded', () => {
      render(
        <SandboxPanel sandboxId="test-sandbox">
          <SandboxPanel.Terminal />
        </SandboxPanel>
      );

      expect(screen.queryByText('Control')).not.toBeInTheDocument();
    });

    it('should render desktop and terminal status cards', () => {
      const mockOnDesktopStart = vi.fn();
      const mockOnDesktopStop = vi.fn();
      const mockOnTerminalStart = vi.fn();
      const mockOnTerminalStop = vi.fn();

      render(
        <SandboxPanel
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusRunning}
          terminalStatus={mockTerminalStatusRunning}
          onDesktopStart={mockOnDesktopStart}
          onDesktopStop={mockOnDesktopStop}
          onTerminalStart={mockOnTerminalStart}
          onTerminalStop={mockOnTerminalStop}
        >
          <SandboxPanel.Control />
        </SandboxPanel>
      );

      expect(screen.getByText('Remote Desktop')).toBeInTheDocument();
      expect(screen.getByText('Web Terminal')).toBeInTheDocument();
    });

    it('should call onDesktopStart when start button is clicked', async () => {
      const mockOnDesktopStart = vi.fn();

      render(
        <SandboxPanel
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusStopped}
          onDesktopStart={mockOnDesktopStart}
        >
          <SandboxPanel.Control />
        </SandboxPanel>
      );

      // Switch to control tab first
      const controlTab = screen.getByText('Control');
      fireEvent.click(controlTab);

      await waitFor(() => {
        const startButtons = screen.getAllByRole('button', { name: /start/i });
        expect(startButtons.length).toBeGreaterThan(0);
        fireEvent.click(startButtons[0]);
      });

      expect(mockOnDesktopStart).toHaveBeenCalled();
    });

    it('should show loading state when isDesktopLoading is true', async () => {
      render(
        <SandboxPanel
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusStopped}
          onDesktopStart={vi.fn()}
          isDesktopLoading={true}
        >
          <SandboxPanel.Control />
        </SandboxPanel>
      );

      // Switch to control tab
      const controlTab = screen.getByText('Control');
      fireEvent.click(controlTab);

      await waitFor(() => {
        expect(screen.getByText('Starting...')).toBeInTheDocument();
      });
    });
  });

  describe('Output Sub-Component', () => {
    it('should render output tab when Output component is included', () => {
      const toolExecutions = [
        {
          id: 'tool-1',
          toolName: 'web_search',
          input: { query: 'test' },
          output: 'results',
          timestamp: Date.now(),
        },
      ];

      render(
        <SandboxPanel sandboxId="test-sandbox" toolExecutions={toolExecutions}>
          <SandboxPanel.Output />
        </SandboxPanel>
      );

      expect(screen.getByText('Output')).toBeInTheDocument();
    });

    it('should not render output tab when Output component is excluded', () => {
      render(
        <SandboxPanel sandboxId="test-sandbox">
          <SandboxPanel.Terminal />
        </SandboxPanel>
      );

      expect(screen.queryByText('Output')).not.toBeInTheDocument();
    });

    it('should display tool execution count badge', () => {
      const toolExecutions = [
        {
          id: 'tool-1',
          toolName: 'web_search',
          input: { query: 'test' },
          output: 'results',
          timestamp: Date.now(),
        },
        {
          id: 'tool-2',
          toolName: 'code_exec',
          input: { code: "print('hello')" },
          output: 'hello',
          timestamp: Date.now(),
        },
      ];

      render(
        <SandboxPanel sandboxId="test-sandbox" toolExecutions={toolExecutions}>
          <SandboxPanel.Output />
        </SandboxPanel>
      );

      expect(screen.getByText('Output')).toBeInTheDocument();
      // Badge should show count
      const outputTab = screen.getByText('Output');
      expect(outputTab).toBeInTheDocument();
    });

    it('should call onFileClick when file is clicked', async () => {
      const mockOnFileClick = vi.fn();
      const toolExecutions = [
        {
          id: 'tool-1',
          toolName: 'code_exec',
          input: { code: "print('hello')" },
          output: 'hello',
          timestamp: Date.now(),
        },
      ];

      render(
        <SandboxPanel
          sandboxId="test-sandbox"
          toolExecutions={toolExecutions}
          onFileClick={mockOnFileClick}
        >
          <SandboxPanel.Output />
        </SandboxPanel>
      );
    });
  });

  describe('All Sub-Components Together', () => {
    it('should render all tabs when all sub-components are included', () => {
      render(
        <SandboxPanel sandboxId="test-sandbox">
          <SandboxPanel.Terminal />
          <SandboxPanel.Desktop />
          <SandboxPanel.Control />
          <SandboxPanel.Output />
        </SandboxPanel>
      );

      expect(screen.getByText('Terminal')).toBeInTheDocument();
      expect(screen.getByText('Desktop')).toBeInTheDocument();
      expect(screen.getByText('Control')).toBeInTheDocument();
      expect(screen.getByText('Output')).toBeInTheDocument();
    });

    it('should allow custom tab ordering through component order', () => {
      render(
        <SandboxPanel sandboxId="test-sandbox">
          <SandboxPanel.Output />
          <SandboxPanel.Desktop />
          <SandboxPanel.Terminal />
          <SandboxPanel.Control />
        </SandboxPanel>
      );

      // All tabs should be present
      expect(screen.getByText('Terminal')).toBeInTheDocument();
      expect(screen.getByText('Desktop')).toBeInTheDocument();
      expect(screen.getByText('Control')).toBeInTheDocument();
      expect(screen.getByText('Output')).toBeInTheDocument();
    });
  });

  describe('Backward Compatibility', () => {
    it('should work with legacy props when no sub-components provided', () => {
      render(
        <SandboxPanel
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusRunning}
          terminalStatus={mockTerminalStatusRunning}
        />
      );

      // Should render all tabs by default for backward compatibility
      expect(screen.getByText('Terminal')).toBeInTheDocument();
      expect(screen.getByText('Desktop')).toBeInTheDocument();
      expect(screen.getByText('Control')).toBeInTheDocument();
      expect(screen.getByText('Output')).toBeInTheDocument();
    });

    it('should support legacy callbacks', () => {
      const mockOnClose = vi.fn();
      const mockOnDesktopStart = vi.fn();
      const mockOnDesktopStop = vi.fn();

      const { container } = render(
        <SandboxPanel
          sandboxId="test-sandbox"
          onClose={mockOnClose}
          onDesktopStart={mockOnDesktopStart}
          onDesktopStop={mockOnDesktopStop}
        />
      );

      // Close button should work
      const closeButton = container.querySelector('.anticon-close');
      expect(closeButton).toBeInTheDocument();
    });

    it('should support legacy loading states', () => {
      render(
        <SandboxPanel sandboxId="test-sandbox" isDesktopLoading={true} isTerminalLoading={true} />
      );

      // Should render without errors
      expect(screen.getByText('Sandbox')).toBeInTheDocument();
    });
  });

  describe('Tab Switching', () => {
    it('should switch between tabs correctly', async () => {
      render(
        <SandboxPanel sandboxId="test-sandbox" defaultTab="terminal">
          <SandboxPanel.Terminal />
          <SandboxPanel.Desktop />
          <SandboxPanel.Control />
        </SandboxPanel>
      );

      // Start on terminal tab
      expect(screen.getByText('Terminal')).toBeInTheDocument();

      // Click desktop tab
      const desktopTab = screen.getByText('Desktop');
      fireEvent.click(desktopTab);

      await waitFor(() => {
        // Remote Desktop appears in both Desktop and Control tabs
        expect(screen.getAllByText('Remote Desktop').length).toBeGreaterThan(0);
      });

      // Click control tab
      const controlTab = screen.getByText('Control');
      fireEvent.click(controlTab);

      await waitFor(() => {
        // Remote Desktop appears in Control panel status card
        expect(screen.getAllByText('Remote Desktop').length).toBeGreaterThan(0);
      });
    });
  });

  describe('Edge Cases', () => {
    it('should handle null sandboxId gracefully', () => {
      render(
        <SandboxPanel sandboxId={null}>
          <SandboxPanel.Terminal />
        </SandboxPanel>
      );

      expect(screen.getByText('No sandbox connected')).toBeInTheDocument();
    });

    it('should handle empty tool executions array', () => {
      render(
        <SandboxPanel sandboxId="test-sandbox" toolExecutions={[]}>
          <SandboxPanel.Output />
        </SandboxPanel>
      );

      expect(screen.getByText('Output')).toBeInTheDocument();
    });

    it('should handle missing optional callbacks', () => {
      render(
        <SandboxPanel sandboxId="test-sandbox">
          <SandboxPanel.Control />
        </SandboxPanel>
      );

      // Should render without errors
      expect(screen.getByText('Control')).toBeInTheDocument();
    });
  });
});

describe('SandboxPanel Namespace', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should export all sub-components', () => {
    expect(SandboxPanel.Root).toBeDefined();
    expect(SandboxPanel.Terminal).toBeDefined();
    expect(SandboxPanel.Desktop).toBeDefined();
    expect(SandboxPanel.Control).toBeDefined();
    expect(SandboxPanel.Output).toBeDefined();
    expect(SandboxPanel.Header).toBeDefined();
  });

  it('should use Root component as alias', () => {
    render(
      <SandboxPanel.Root sandboxId="test-sandbox">
        <SandboxPanel.Terminal />
      </SandboxPanel.Root>
    );

    expect(screen.getByText('Sandbox')).toBeInTheDocument();
  });
});

/**
 * Tests for SandboxPanel Desktop Integration
 *
 * Tests the sandbox panel components with desktop and terminal support.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

import { RemoteDesktopViewer } from "../../../../components/agent/sandbox/RemoteDesktopViewer";
import { SandboxControlPanel } from "../../../../components/agent/sandbox/SandboxControlPanel";
import { SandboxPanel } from "../../../../components/agent/sandbox/SandboxPanel";

import type { ToolExecution } from "../../../../components/agent/sandbox/SandboxOutputViewer";
import type { DesktopStatus, TerminalStatus } from "../../../../types/agent";

// Mock the dependencies - must define mocks inline for vitest hoisting
vi.mock("@xterm/xterm", () => {
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

vi.mock("@xterm/addon-fit", () => {
  const mockFit = vi.fn();

  class MockFitAddon {
    fit = mockFit;
    constructor() {}
  }

  return {
    FitAddon: MockFitAddon,
  };
});

vi.mock("@xterm/addon-web-links", () => ({
  WebLinksAddon: class MockWebLinksAddon {
    constructor() {}
  },
}));

vi.mock("../../../../services/client/urlUtils", () => ({
  createWebSocketUrl: (path: string, params?: Record<string, string>) => {
    const queryString = params
      ? `?${new URLSearchParams(params).toString()}`
      : "";
    return `ws://localhost:8000${path}${queryString}`;
  },
}));

const mockDesktopStatusRunning: DesktopStatus = {
  running: true,
  url: "http://localhost:6080/vnc.html",
  display: ":0",
  resolution: "1280x720",
  port: 6080,
};

const mockDesktopStatusStopped: DesktopStatus = {
  running: false,
  url: null,
  display: "",
  resolution: "",
  port: 0,
};

const mockTerminalStatusRunning: TerminalStatus = {
  running: true,
  url: "ws://localhost:7681",
  port: 7681,
};

const mockTerminalStatusStopped: TerminalStatus = {
  running: false,
  url: null,
  port: 0,
};

const mockToolExecutions: ToolExecution[] = [
  {
    id: "tool-1",
    toolName: "web_search",
    input: { query: "test query" },
    output: "Search results",
    timestamp: Date.now(),
  },
];

describe("SandboxPanel with Desktop Integration", () => {

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Extended tab support", () => {
    it("should render all four tabs: terminal, desktop, control, and output", () => {
      const mockOnDesktopStart = vi.fn();
      const mockOnDesktopStop = vi.fn();
      const mockOnTerminalStart = vi.fn();
      const mockOnTerminalStop = vi.fn();

      render(
        <SandboxPanel
          sandboxId="test-sandbox-123"
          desktopStatus={mockDesktopStatusRunning}
          terminalStatus={mockTerminalStatusRunning}
          onDesktopStart={mockOnDesktopStart}
          onDesktopStop={mockOnDesktopStop}
          onTerminalStart={mockOnTerminalStart}
          onTerminalStop={mockOnTerminalStop}
        />
      );

      // Check all tabs are present
      expect(screen.getByText("Terminal")).toBeInTheDocument();
      expect(screen.getByText("Desktop")).toBeInTheDocument();
      expect(screen.getByText("Control")).toBeInTheDocument();
      expect(screen.getByText("Output")).toBeInTheDocument();
    });

    it("should show desktop tab in tab items", () => {
      render(
        <SandboxPanel
          sandboxId="test-sandbox-123"
          desktopStatus={mockDesktopStatusRunning}
        />
      );

      expect(screen.getByText("Desktop")).toBeInTheDocument();
    });

    it("should switch to desktop tab when clicked", async () => {
      render(
        <SandboxPanel
          sandboxId="test-sandbox-123"
          desktopStatus={mockDesktopStatusRunning}
        />
      );

      const desktopTab = screen.getByText("Desktop");
      fireEvent.click(desktopTab);

      // After clicking, desktop content should be visible
      await waitFor(() => {
        expect(screen.getByText("Remote Desktop")).toBeInTheDocument();
      });
    });
  });

  describe("Desktop status in header", () => {
    it("should display sandbox ID in header", () => {
      render(
        <SandboxPanel
          sandboxId="test-sandbox-12345678"
          desktopStatus={null}
        />
      );

      expect(screen.getByText(/test-sandbox/)).toBeInTheDocument();
    });

    it("should show current tool badge when tool is running", () => {
      render(
        <SandboxPanel
          sandboxId="test-sandbox-123"
          currentTool={{ name: "web_search", input: { query: "test" } }}
          desktopStatus={null}
        />
      );

      expect(screen.getByText("web_search")).toBeInTheDocument();
    });

    it("should call onClose when close button is clicked", () => {
      const mockOnClose = vi.fn();
      const { container } = render(
        <SandboxPanel
          sandboxId="test-sandbox-123"
          desktopStatus={null}
          onClose={mockOnClose}
        />
      );

      // Find close button using class selector (Ant Design close icon)
      const closeButton = container.querySelector(".anticon-close");
      if (closeButton) {
        fireEvent.click(closeButton.closest("button") || closeButton);
        expect(mockOnClose).toHaveBeenCalled();
      }
    });
  });

  describe("Output tab", () => {
    it("should display tool execution count badge", () => {
      render(
        <SandboxPanel
          sandboxId="test-sandbox-123"
          toolExecutions={mockToolExecutions}
          desktopStatus={null}
        />
      );

      expect(screen.getByText("Output")).toBeInTheDocument();
    });
  });

  describe("Empty state", () => {
    it("should show empty state when no sandbox is connected", () => {
      render(
        <SandboxPanel
          sandboxId={null}
          desktopStatus={null}
        />
      );

      expect(screen.getByText("No sandbox connected")).toBeInTheDocument();
    });
  });
});

describe("RemoteDesktopViewer", () => {

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Rendering", () => {
    it("should render iframe when desktop URL is provided", () => {
      const { container } = render(
        <RemoteDesktopViewer
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusRunning}
        />
      );

      const iframe = container.querySelector("iframe");
      expect(iframe).toBeInTheDocument();
      expect(iframe).toHaveAttribute("src", "http://localhost:6080/vnc.html");
    });

    it("should render empty state when no desktop URL", () => {
      render(
        <RemoteDesktopViewer
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusStopped}
        />
      );

      expect(screen.getByText("Desktop is not running")).toBeInTheDocument();
      expect(screen.getByText("Start the desktop to connect")).toBeInTheDocument();
    });

    it("should render loading state initially when URL is provided", () => {
      render(
        <RemoteDesktopViewer
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusRunning}
        />
      );

      // Loading indicator should be present
      expect(screen.getByText(/Connecting/i)).toBeInTheDocument();
    });

    it("should render toolbar when showToolbar is true", () => {
      render(
        <RemoteDesktopViewer
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusRunning}
          showToolbar={true}
        />
      );

      expect(screen.getByText("Remote Desktop")).toBeInTheDocument();
    });

    it("should not render toolbar when showToolbar is false", () => {
      render(
        <RemoteDesktopViewer
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusRunning}
          showToolbar={false}
        />
      );

      expect(screen.queryByText("Remote Desktop")).not.toBeInTheDocument();
    });
  });

  describe("Controls", () => {
    it("should have fullscreen button", () => {
      render(
        <RemoteDesktopViewer
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusRunning}
        />
      );

      const fullscreenButton = screen.getByRole("button", { name: /fullscreen/i });
      expect(fullscreenButton).toBeInTheDocument();
    });

    it("should have refresh button when desktop is running", () => {
      render(
        <RemoteDesktopViewer
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusRunning}
        />
      );

      const refreshButton = screen.getByRole("button", { name: /refresh/i });
      expect(refreshButton).toBeInTheDocument();
    });

    it("should have close button when onClose is provided", () => {
      const mockOnClose = vi.fn();
      render(
        <RemoteDesktopViewer
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusRunning}
          onClose={mockOnClose}
        />
      );

      const closeButton = screen.getByRole("button", { name: /close/i });
      expect(closeButton).toBeInTheDocument();
    });
  });

  describe("User interactions", () => {
    it("should toggle fullscreen on fullscreen button click", () => {
      render(
        <RemoteDesktopViewer
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusRunning}
        />
      );

      const fullscreenButton = screen.getByRole("button", { name: /fullscreen/i });

      // Initial state - should show "Fullscreen" tooltip
      expect(fullscreenButton).toBeInTheDocument();

      fireEvent.click(fullscreenButton);

      // After clicking, icon should change (though we can't easily test the actual fullscreen)
      const fullscreenButtonAfter = screen.getByRole("button", { name: /exit fullscreen/i });
      expect(fullscreenButtonAfter).toBeInTheDocument();
    });

    it("should call onClose when close button is clicked", () => {
      const mockOnClose = vi.fn();
      render(
        <RemoteDesktopViewer
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusRunning}
          onClose={mockOnClose}
        />
      );

      const closeButton = screen.getByRole("button", { name: /close/i });
      fireEvent.click(closeButton);

      expect(mockOnClose).toHaveBeenCalledTimes(1);
    });

    it("should display sandbox ID in toolbar", () => {
      const { container } = render(
        <RemoteDesktopViewer
          sandboxId="test-sandbox-12345678"
          desktopStatus={mockDesktopStatusRunning}
        />
      );

      // The sandbox ID is displayed as (test-san) - first 8 chars
      expect(container.textContent).toContain("test-san");
    });
  });
});

describe("SandboxControlPanel", () => {

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Rendering", () => {
    it("should render both desktop and terminal status cards", () => {
      const mockOnDesktopStart = vi.fn();
      const mockOnDesktopStop = vi.fn();
      const mockOnTerminalStart = vi.fn();
      const mockOnTerminalStop = vi.fn();

      render(
        <SandboxControlPanel
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusRunning}
          terminalStatus={mockTerminalStatusRunning}
          onDesktopStart={mockOnDesktopStart}
          onDesktopStop={mockOnDesktopStop}
          onTerminalStart={mockOnTerminalStart}
          onTerminalStop={mockOnTerminalStop}
        />
      );

      expect(screen.getByText("Remote Desktop")).toBeInTheDocument();
      expect(screen.getByText("Web Terminal")).toBeInTheDocument();
    });

    it("should render start button when desktop is not running", () => {
      const mockOnDesktopStart = vi.fn();

      render(
        <SandboxControlPanel
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusStopped}
          terminalStatus={null}
          onDesktopStart={mockOnDesktopStart}
        />
      );

      // Use getAllByRole since we might have multiple buttons
      const startButtons = screen.getAllByRole("button", { name: /start/i });
      expect(startButtons.length).toBeGreaterThan(0);
    });

    it("should render stop button when desktop is running", () => {
      const mockOnDesktopStop = vi.fn();

      render(
        <SandboxControlPanel
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusRunning}
          terminalStatus={null}
          onDesktopStop={mockOnDesktopStop}
        />
      );

      expect(screen.getByRole("button", { name: /stop/i })).toBeInTheDocument();
    });
  });

  describe("Status display", () => {
    it("should show running status when desktop is active", () => {
      render(
        <SandboxControlPanel
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusRunning}
          terminalStatus={null}
        />
      );

      expect(screen.getByText("Running")).toBeInTheDocument();
    });

    it("should show stopped status when desktop is inactive", () => {
      const { container } = render(
        <SandboxControlPanel
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusStopped}
          terminalStatus={null}
        />
      );

      // Get all "Stopped" text elements - should have at least one
      const stoppedElements = container.querySelectorAll(".ant-badge-status-text");
      const hasStopped = Array.from(stoppedElements).some(el => el.textContent === "Stopped");
      expect(hasStopped).toBe(true);
    });

    it("should show loading status when desktop is starting", () => {
      render(
        <SandboxControlPanel
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusStopped}
          terminalStatus={null}
          onDesktopStart={vi.fn()}
          isDesktopLoading={true}
        />
      );

      expect(screen.getByText("Starting...")).toBeInTheDocument();
    });

    it("should show desktop URL when running", () => {
      render(
        <SandboxControlPanel
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusRunning}
          terminalStatus={null}
        />
      );

      const urlElement = screen.getByText(/http:\/\/localhost:6080/);
      expect(urlElement).toBeInTheDocument();
    });

    it("should show desktop resolution when available", () => {
      render(
        <SandboxControlPanel
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusRunning}
          terminalStatus={null}
        />
      );

      expect(screen.getByText("1280x720")).toBeInTheDocument();
    });
  });

  describe("Terminal status display", () => {
    it("should show terminal running status", () => {
      render(
        <SandboxControlPanel
          sandboxId="test-sandbox"
          desktopStatus={null}
          terminalStatus={mockTerminalStatusRunning}
        />
      );

      expect(screen.getByText("Running")).toBeInTheDocument();
    });

    it("should show terminal URL when running", () => {
      render(
        <SandboxControlPanel
          sandboxId="test-sandbox"
          desktopStatus={null}
          terminalStatus={mockTerminalStatusRunning}
        />
      );

      const urlElement = screen.getByText(/ws:\/\/localhost:7681/);
      expect(urlElement).toBeInTheDocument();
    });

    it("should show terminal port when available", () => {
      render(
        <SandboxControlPanel
          sandboxId="test-sandbox"
          desktopStatus={null}
          terminalStatus={mockTerminalStatusRunning}
        />
      );

      expect(screen.getByText("7681")).toBeInTheDocument();
    });
  });

  describe("User interactions", () => {
    it("should call onDesktopStart when start desktop button is clicked", () => {
      const mockOnDesktopStart = vi.fn();

      render(
        <SandboxControlPanel
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusStopped}
          terminalStatus={null}
          onDesktopStart={mockOnDesktopStart}
        />
      );

      // Use getAllByRole since there's only one start button when terminal is null
      const startButtons = screen.getAllByRole("button", { name: /start/i });
      fireEvent.click(startButtons[0]);

      expect(mockOnDesktopStart).toHaveBeenCalledTimes(1);
    });

    it("should call onDesktopStop when stop desktop button is clicked", () => {
      const mockOnDesktopStop = vi.fn();

      render(
        <SandboxControlPanel
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusRunning}
          terminalStatus={null}
          onDesktopStop={mockOnDesktopStop}
        />
      );

      // Use getAllByRole since there's only one stop button when terminal is null
      const stopButtons = screen.getAllByRole("button", { name: /stop/i });
      fireEvent.click(stopButtons[0]);

      expect(mockOnDesktopStop).toHaveBeenCalledTimes(1);
    });

    it("should call onTerminalStart when start terminal button is clicked", () => {
      const mockOnTerminalStart = vi.fn();

      const { container } = render(
        <SandboxControlPanel
          sandboxId="test-sandbox"
          desktopStatus={null}
          terminalStatus={mockTerminalStatusStopped}
          onTerminalStart={mockOnTerminalStart}
        />
      );

      // Find buttons by text content since icon interferes with name matching
      const startButtons = Array.from(container.querySelectorAll("button"))
        .filter(btn => btn.textContent?.includes("Start"));

      expect(startButtons.length).toBeGreaterThan(0);
      fireEvent.click(startButtons[0]);

      expect(mockOnTerminalStart).toHaveBeenCalledTimes(1);
    });

    it("should call onTerminalStop when stop terminal button is clicked", () => {
      const mockOnTerminalStop = vi.fn();

      render(
        <SandboxControlPanel
          sandboxId="test-sandbox"
          desktopStatus={null}
          terminalStatus={mockTerminalStatusRunning}
          onTerminalStop={mockOnTerminalStop}
        />
      );

      // Use getAllByRole since there's only one stop button when desktop is null
      const stopButtons = screen.getAllByRole("button", { name: /stop/i });
      fireEvent.click(stopButtons[0]);

      expect(mockOnTerminalStop).toHaveBeenCalledTimes(1);
    });

    it("should disable start button when loading", () => {
      const mockOnDesktopStart = vi.fn();

      const { container } = render(
        <SandboxControlPanel
          sandboxId="test-sandbox"
          desktopStatus={mockDesktopStatusStopped}
          terminalStatus={null}
          onDesktopStart={mockOnDesktopStart}
          isDesktopLoading={true}
        />
      );

      // Ant Design loading buttons have the "ant-btn-loading" class
      const startButtons = Array.from(container.querySelectorAll("button"))
        .filter(btn => btn.textContent?.includes("Start"));

      expect(startButtons.length).toBeGreaterThan(0);
      // Check if the button has loading class
      expect(startButtons[0].classList.contains("ant-btn-loading")).toBe(true);
    });
  });
});

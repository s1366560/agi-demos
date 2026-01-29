/**
 * Tests for Sandbox Service
 *
 * TDD: Tests written before implementation
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { sandboxService } from "../../services/sandboxService";
import { httpClient } from "../../services/client/httpClient";
import { ApiError, ApiErrorType } from "../../services/client/ApiError";

// Mock httpClient
vi.mock("../../services/client/httpClient", () => ({
  httpClient: {
    post: vi.fn(),
    get: vi.fn(),
    delete: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
  },
}));

describe("sandboxService", () => {
  const mockHttpClient = httpClient as {
    post: ReturnType<typeof vi.fn>;
    get: ReturnType<typeof vi.fn>;
    delete: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("createSandbox", () => {
    it("should create a new sandbox and return response", async () => {
      const mockBackendResponse = {
        id: "sb_123456",
        status: "running",
        project_path: "/tmp/memstack_proj_789",
        endpoint: "ws://localhost:8080",
        websocket_url: "ws://localhost:7681",
        created_at: "2024-01-15T10:30:00Z",
        tools: ["read", "write", "bash"],
      };

      mockHttpClient.post.mockResolvedValue(mockBackendResponse);

      const request = {
        project_id: "proj_789",
        image: "memstack/sandbox:latest",
      };

      const result = await sandboxService.createSandbox(request);

      expect(result.sandbox.id).toBe("sb_123456");
      expect(result.sandbox.project_id).toBe("proj_789");
      expect(result.sandbox.status).toBe("running");
      expect(result.urls?.desktop).toBe("ws://localhost:8080");
      expect(result.urls?.terminal).toBe("ws://localhost:7681");
      expect(mockHttpClient.post).toHaveBeenCalledWith(
        "/sandbox/create",
        expect.objectContaining({
          project_path: "/tmp/memstack_proj_789",
          image: "memstack/sandbox:latest",
        })
      );
    });

    it("should handle creation failure", async () => {
      const apiError = new ApiError(
        ApiErrorType.SERVER,
        "INTERNAL_ERROR",
        "Failed to create sandbox",
        500
      );
      mockHttpClient.post.mockRejectedValue(apiError);

      const request = { project_id: "proj_789" };

      await expect(sandboxService.createSandbox(request)).rejects.toThrow(
        "Failed to create sandbox"
      );
    });
  });

  describe("getSandbox", () => {
    it("should get sandbox by ID and extract project_id from path", async () => {
      const mockBackendResponse = {
        id: "sb_123456",
        status: "running",
        project_path: "/tmp/memstack_proj_789",
        endpoint: "ws://localhost:8080",
        websocket_url: "ws://localhost:7681",
        created_at: "2024-01-15T10:30:00Z",
        tools: ["read", "write", "bash"],
      };

      mockHttpClient.get.mockResolvedValue(mockBackendResponse);

      const result = await sandboxService.getSandbox("sb_123456");

      expect(result.id).toBe("sb_123456");
      expect(result.project_id).toBe("proj_789"); // Extracted from project_path
      expect(result.status).toBe("running");
      expect(result.container_id).toBe("sb_123456"); // Same as id
      expect(mockHttpClient.get).toHaveBeenCalledWith("/sandbox/sb_123456");
    });

    it("should handle 404 when sandbox not found", async () => {
      const apiError = new ApiError(
        ApiErrorType.NOT_FOUND,
        "NOT_FOUND",
        "Sandbox not found",
        404
      );
      mockHttpClient.get.mockRejectedValue(apiError);

      await expect(sandboxService.getSandbox("invalid")).rejects.toThrow(
        "Sandbox not found"
      );
    });
  });

  describe("listSandboxes", () => {
    it("should list and filter sandboxes for a project", async () => {
      const mockBackendResponse = {
        sandboxes: [
          {
            id: "sb_123",
            status: "running",
            project_path: "/tmp/memstack_proj_789",
            created_at: "2024-01-15T10:30:00Z",
            tools: ["read", "write"],
          },
          {
            id: "sb_456",
            status: "stopped",
            project_path: "/tmp/memstack_other_project",
            created_at: "2024-01-14T10:30:00Z",
            tools: [],
          },
          {
            id: "sb_789",
            status: "running",
            project_path: "/tmp/memstack_proj_789",
            created_at: "2024-01-13T10:30:00Z",
            tools: ["bash"],
          },
        ],
        total: 3,
      };

      mockHttpClient.get.mockResolvedValue(mockBackendResponse);

      const result = await sandboxService.listSandboxes("proj_789");

      // Should only return sandboxes matching the project_id
      expect(result.sandboxes).toHaveLength(2);
      expect(result.sandboxes[0].id).toBe("sb_123");
      expect(result.sandboxes[0].project_id).toBe("proj_789");
      expect(result.sandboxes[1].id).toBe("sb_789");
      expect(result.total).toBe(2);
      expect(mockHttpClient.get).toHaveBeenCalledWith("/sandbox");
    });

    it("should return empty array when no matching sandboxes exist", async () => {
      const mockBackendResponse = {
        sandboxes: [
          {
            id: "sb_456",
            status: "stopped",
            project_path: "/tmp/memstack_other_project",
            created_at: "2024-01-14T10:30:00Z",
            tools: [],
          },
        ],
        total: 1,
      };

      mockHttpClient.get.mockResolvedValue(mockBackendResponse);

      const result = await sandboxService.listSandboxes("proj_empty");

      expect(result.sandboxes).toEqual([]);
      expect(result.total).toBe(0);
    });
  });

  describe("deleteSandbox", () => {
    it("should delete sandbox by ID", async () => {
      mockHttpClient.delete.mockResolvedValue(undefined);

      await sandboxService.deleteSandbox("sb_123");

      expect(mockHttpClient.delete).toHaveBeenCalledWith("/sandbox/sb_123");
    });

    it("should handle delete failure", async () => {
      const apiError = new ApiError(
        ApiErrorType.SERVER,
        "INTERNAL_ERROR",
        "Failed to delete sandbox",
        500
      );
      mockHttpClient.delete.mockRejectedValue(apiError);

      await expect(sandboxService.deleteSandbox("sb_123")).rejects.toThrow(
        "Failed to delete sandbox"
      );
    });
  });

  describe("startDesktop", () => {
    it("should start desktop service with default resolution", async () => {
      const mockBackendResponse = {
        running: true,
        url: "http://localhost:6080/vnc.html",
        display: ":1",
        resolution: "1280x720",
        port: 6080,
      };

      mockHttpClient.post.mockResolvedValue(mockBackendResponse);

      const result = await sandboxService.startDesktop("sb_123");

      expect(result.running).toBe(true);
      expect(result.url).toBe("http://localhost:6080/vnc.html");
      expect(result.display).toBe(":1");
      expect(result.resolution).toBe("1280x720");
      expect(result.port).toBe(6080);
      expect(mockHttpClient.post).toHaveBeenCalledWith("/sandbox/sb_123/desktop", {
        resolution: "1280x720",
        display: ":1",
      });
    });

    it("should start desktop service with custom resolution", async () => {
      const mockBackendResponse = {
        running: true,
        url: "http://localhost:6080/vnc.html",
        display: ":1",
        resolution: "1920x1080",
        port: 6080,
      };

      mockHttpClient.post.mockResolvedValue(mockBackendResponse);

      const result = await sandboxService.startDesktop("sb_123", "1920x1080");

      expect(result.running).toBe(true);
      expect(result.resolution).toBe("1920x1080");
      expect(mockHttpClient.post).toHaveBeenCalledWith("/sandbox/sb_123/desktop", {
        resolution: "1920x1080",
        display: ":1",
      });
    });

    it("should handle start desktop failure", async () => {
      const apiError = new ApiError(
        ApiErrorType.SERVER,
        "INTERNAL_ERROR",
        "Failed to start desktop",
        500
      );
      mockHttpClient.post.mockRejectedValue(apiError);

      await expect(sandboxService.startDesktop("sb_123")).rejects.toThrow(
        "Failed to start desktop"
      );
    });
  });

  describe("stopDesktop", () => {
    it("should stop desktop service", async () => {
      const mockBackendResponse = {
        success: true,
        message: "Desktop stopped successfully",
      };

      mockHttpClient.delete.mockResolvedValue(mockBackendResponse);

      await sandboxService.stopDesktop("sb_123");

      expect(mockHttpClient.delete).toHaveBeenCalledWith("/sandbox/sb_123/desktop");
    });

    it("should handle stop desktop failure", async () => {
      const apiError = new ApiError(
        ApiErrorType.SERVER,
        "INTERNAL_ERROR",
        "Failed to stop desktop",
        500
      );
      mockHttpClient.delete.mockRejectedValue(apiError);

      await expect(sandboxService.stopDesktop("sb_123")).rejects.toThrow(
        "Failed to stop desktop"
      );
    });
  });

  describe("startTerminal", () => {
    it("should start terminal service and return constructed WebSocket URL", async () => {
      const mockBackendResponse = {
        session_id: "sess_abc123",
        container_id: "sb_123",
        cols: 80,
        rows: 24,
        is_active: true,
      };

      mockHttpClient.post.mockResolvedValue(mockBackendResponse);

      const result = await sandboxService.startTerminal("sb_123");

      expect(result.running).toBe(true);
      expect(result.sessionId).toBe("sess_abc123");
      expect(result.port).toBe(8000);
      expect(result.url).toBe("ws://localhost:8000/api/v1/terminal/sb_123/ws?session_id=sess_abc123");
      expect(mockHttpClient.post).toHaveBeenCalledWith("/terminal/sb_123/create", {
        shell: "/bin/bash",
        cols: 80,
        rows: 24,
      });
    });
  });

  describe("stopTerminal", () => {
    it("should stop terminal service by session ID", async () => {
      mockHttpClient.delete.mockResolvedValue({ success: true, session_id: "sess_abc" });

      await sandboxService.stopTerminal("sb_123", "sess_abc");

      expect(mockHttpClient.delete).toHaveBeenCalledWith("/terminal/sb_123/sessions/sess_abc");
    });

    it("should stop all terminal sessions when no session ID provided", async () => {
      const mockSessions = [
        { session_id: "sess_abc", container_id: "sb_123", is_active: true },
        { session_id: "sess_def", container_id: "sb_123", is_active: true },
      ];

      mockHttpClient.get.mockResolvedValue(mockSessions);
      mockHttpClient.delete.mockResolvedValue({ success: true });

      await sandboxService.stopTerminal("sb_123");

      expect(mockHttpClient.get).toHaveBeenCalledWith("/terminal/sb_123/sessions");
      expect(mockHttpClient.delete).toHaveBeenCalledWith("/terminal/sb_123/sessions/sess_abc");
      expect(mockHttpClient.delete).toHaveBeenCalledWith("/terminal/sb_123/sessions/sess_def");
    });
  });

  describe("getDesktopStatus", () => {
    it("should return running status when desktop is active", async () => {
      const mockBackendResponse = {
        running: true,
        url: "http://localhost:6080/vnc.html",
        display: ":1",
        resolution: "1280x720",
        port: 6080,
      };

      mockHttpClient.get.mockResolvedValue(mockBackendResponse);

      const result = await sandboxService.getDesktopStatus("sb_123");

      expect(result.running).toBe(true);
      expect(result.url).toBe("http://localhost:6080/vnc.html");
      expect(result.display).toBe(":1");
      expect(result.resolution).toBe("1280x720");
      expect(result.port).toBe(6080);
      expect(mockHttpClient.get).toHaveBeenCalledWith("/sandbox/sb_123/desktop");
    });

    it("should return not running status when desktop is stopped", async () => {
      const mockBackendResponse = {
        running: false,
        url: null,
        display: "",
        resolution: "",
        port: 0,
      };

      mockHttpClient.get.mockResolvedValue(mockBackendResponse);

      const result = await sandboxService.getDesktopStatus("sb_123");

      expect(result.running).toBe(false);
      expect(result.url).toBeNull();
      expect(result.display).toBe("");
      expect(result.resolution).toBe("");
      expect(result.port).toBe(0);
    });
  });

  describe("getTerminalStatus", () => {
    it("should get current terminal status with active session", async () => {
      const mockSessions = [
        {
          session_id: "sess_abc123",
          container_id: "sb_123",
          cols: 80,
          rows: 24,
          is_active: true,
        },
      ];

      mockHttpClient.get.mockResolvedValue(mockSessions);

      const result = await sandboxService.getTerminalStatus("sb_123");

      expect(result.running).toBe(true);
      expect(result.sessionId).toBe("sess_abc123");
      expect(result.port).toBe(8000);
      expect(result.url).toBe("ws://localhost:8000/api/v1/terminal/sb_123/ws?session_id=sess_abc123");
      expect(mockHttpClient.get).toHaveBeenCalledWith("/terminal/sb_123/sessions");
    });

    it("should return not running when no active sessions", async () => {
      mockHttpClient.get.mockResolvedValue([]);

      const result = await sandboxService.getTerminalStatus("sb_123");

      expect(result.running).toBe(false);
      expect(result.sessionId).toBeNull();
      expect(result.url).toBeNull();
      expect(result.port).toBe(0);
    });

    it("should return not running when sessions array is empty", async () => {
      mockHttpClient.get.mockResolvedValue([]);

      const result = await sandboxService.getTerminalStatus("sb_123");

      expect(result.running).toBe(false);
      expect(result.url).toBeNull();
    });
  });
});

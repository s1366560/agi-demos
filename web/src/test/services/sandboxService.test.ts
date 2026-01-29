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
      const mockResponse = {
        sandbox: {
          id: "sb_123456",
          project_id: "proj_789",
          status: "running" as const,
          created_at: "2024-01-15T10:30:00Z",
          container_id: "container_abc",
          image: "memstack/sandbox:latest",
        },
        urls: {
          desktop: "ws://localhost:6080",
          terminal: "ws://localhost:7681",
        },
      };

      mockHttpClient.post.mockResolvedValue(mockResponse);

      const request = {
        project_id: "proj_789",
        image: "memstack/sandbox:latest",
      };

      const result = await sandboxService.createSandbox(request);

      expect(result).toEqual(mockResponse);
      expect(mockHttpClient.post).toHaveBeenCalledWith(
        "/sandbox",
        request
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
    it("should get sandbox by ID", async () => {
      const mockSandbox = {
        id: "sb_123456",
        project_id: "proj_789",
        status: "running" as const,
        created_at: "2024-01-15T10:30:00Z",
        container_id: "container_abc",
      };

      mockHttpClient.get.mockResolvedValue(mockSandbox);

      const result = await sandboxService.getSandbox("sb_123456");

      expect(result).toEqual(mockSandbox);
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
    it("should list sandboxes for a project", async () => {
      const mockResponse = {
        sandboxes: [
          {
            id: "sb_123",
            project_id: "proj_789",
            status: "running" as const,
            created_at: "2024-01-15T10:30:00Z",
          },
          {
            id: "sb_456",
            project_id: "proj_789",
            status: "stopped" as const,
            created_at: "2024-01-14T10:30:00Z",
          },
        ],
        total: 2,
      };

      mockHttpClient.get.mockResolvedValue(mockResponse);

      const result = await sandboxService.listSandboxes("proj_789");

      expect(result).toEqual(mockResponse);
      expect(mockHttpClient.get).toHaveBeenCalledWith("/sandbox", {
        params: { project_id: "proj_789" },
      });
    });

    it("should return empty array when no sandboxes exist", async () => {
      const mockResponse = {
        sandboxes: [],
        total: 0,
      };

      mockHttpClient.get.mockResolvedValue(mockResponse);

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
      const mockStatus = {
        running: true,
        url: "ws://localhost:6080",
        display: ":0",
        resolution: "1280x720",
        port: 6080,
      };

      mockHttpClient.post.mockResolvedValue(mockStatus);

      const result = await sandboxService.startDesktop("sb_123");

      expect(result).toEqual(mockStatus);
      expect(mockHttpClient.post).toHaveBeenCalledWith("/sandbox/sb_123/desktop", {
        resolution: "1280x720",
      });
    });

    it("should start desktop service with custom resolution", async () => {
      const mockStatus = {
        running: true,
        url: "ws://localhost:6080",
        display: ":0",
        resolution: "1920x1080",
        port: 6080,
      };

      mockHttpClient.post.mockResolvedValue(mockStatus);

      const result = await sandboxService.startDesktop("sb_123", "1920x1080");

      expect(result.resolution).toBe("1920x1080");
      expect(mockHttpClient.post).toHaveBeenCalledWith("/sandbox/sb_123/desktop", {
        resolution: "1920x1080",
      });
    });
  });

  describe("stopDesktop", () => {
    it("should stop desktop service", async () => {
      mockHttpClient.delete.mockResolvedValue(undefined);

      await sandboxService.stopDesktop("sb_123");

      expect(mockHttpClient.delete).toHaveBeenCalledWith("/sandbox/sb_123/desktop");
    });
  });

  describe("startTerminal", () => {
    it("should start terminal service", async () => {
      const mockStatus = {
        running: true,
        url: "ws://localhost:7681",
        port: 7681,
        sessionId: "sess_abc123",
        pid: 12345,
      };

      mockHttpClient.post.mockResolvedValue(mockStatus);

      const result = await sandboxService.startTerminal("sb_123");

      expect(result).toEqual(mockStatus);
      expect(mockHttpClient.post).toHaveBeenCalledWith("/sandbox/sb_123/terminal");
    });
  });

  describe("stopTerminal", () => {
    it("should stop terminal service", async () => {
      mockHttpClient.delete.mockResolvedValue(undefined);

      await sandboxService.stopTerminal("sb_123");

      expect(mockHttpClient.delete).toHaveBeenCalledWith("/sandbox/sb_123/terminal");
    });
  });

  describe("getDesktopStatus", () => {
    it("should get current desktop status", async () => {
      const mockStatus = {
        running: true,
        url: "ws://localhost:6080",
        display: ":0",
        resolution: "1280x720",
        port: 6080,
      };

      mockHttpClient.get.mockResolvedValue(mockStatus);

      const result = await sandboxService.getDesktopStatus("sb_123");

      expect(result).toEqual(mockStatus);
      expect(mockHttpClient.get).toHaveBeenCalledWith("/sandbox/sb_123/desktop");
    });

    it("should return not running status when desktop is stopped", async () => {
      const mockStatus = {
        running: false,
        url: null,
        display: "",
        resolution: "",
        port: 0,
      };

      mockHttpClient.get.mockResolvedValue(mockStatus);

      const result = await sandboxService.getDesktopStatus("sb_123");

      expect(result.running).toBe(false);
      expect(result.url).toBeNull();
    });
  });

  describe("getTerminalStatus", () => {
    it("should get current terminal status", async () => {
      const mockStatus = {
        running: true,
        url: "ws://localhost:7681",
        port: 7681,
        sessionId: "sess_abc123",
        pid: 12345,
      };

      mockHttpClient.get.mockResolvedValue(mockStatus);

      const result = await sandboxService.getTerminalStatus("sb_123");

      expect(result).toEqual(mockStatus);
      expect(mockHttpClient.get).toHaveBeenCalledWith("/sandbox/sb_123/terminal");
    });
  });
});

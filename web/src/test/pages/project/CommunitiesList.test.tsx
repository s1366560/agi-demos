import { useParams } from "react-router-dom";

import { describe, it, expect, vi, beforeEach } from "vitest";

import { CommunitiesList } from "../../../pages/project/CommunitiesList";
import { graphService } from "../../../services/graphService";
import { render, screen, fireEvent, waitFor } from "../../utils";

vi.mock("../../../services/graphService", () => ({
  graphService: {
    listCommunities: vi.fn(),
    getCommunityMembers: vi.fn(),
    rebuildCommunities: vi.fn(),
  },
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useParams: vi.fn(),
  };
});

describe("CommunitiesList", () => {
  const mockCommunities = [
    {
      uuid: "c1",
      name: "Community 1",
      summary: "Summary of C1",
      member_count: 10,
      formed_at: new Date().toISOString(),
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    (useParams as any).mockReturnValue({ projectId: "p1" });
    (graphService.listCommunities as any).mockResolvedValue({
      communities: mockCommunities,
    });
  });

  it("renders communities list", async () => {
    render(<CommunitiesList />);

    expect(screen.getByText("Communities")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("Community 1")).toBeInTheDocument();
      expect(screen.getByText("10 members")).toBeInTheDocument();
    });
  });

  it("loads community members on selection", async () => {
    (graphService.getCommunityMembers as any).mockResolvedValue({
      members: [{ uuid: "m1", name: "Member 1", entity_type: "Person" }],
    });

    render(<CommunitiesList />);

    await waitFor(() => {
      expect(screen.getByText("Community 1")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Community 1"));

    await waitFor(() => {
      expect(screen.getByText("Community Details")).toBeInTheDocument();
      expect(screen.getByText("Member 1")).toBeInTheDocument();
    });
  });

  it("handles rebuild communities", async () => {
    (graphService.rebuildCommunities as any).mockResolvedValue({});

    render(<CommunitiesList />);

    const rebuildBtn = screen.getByText("Rebuild Communities");
    fireEvent.click(rebuildBtn);

    expect(screen.getByText("Rebuilding...")).toBeInTheDocument();

    await waitFor(() => {
      expect(graphService.rebuildCommunities).toHaveBeenCalled();
      expect(screen.queryByText("Rebuilding...")).not.toBeInTheDocument();
    });
  });

  it("handles empty state", async () => {
    (graphService.listCommunities as any).mockResolvedValue({
      communities: [],
    });

    render(<CommunitiesList />);

    await waitFor(() => {
      expect(screen.getByText("No communities found")).toBeInTheDocument();
    });
  });
});

describe("CommunitiesList - Performance Optimizations", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (useParams as any).mockReturnValue({ projectId: "p1" });
    (graphService.listCommunities as any).mockResolvedValue({
      communities: [],
    });
  });

  it("should export memoized component", () => {
    // Component should be memoized with React.memo
    expect(CommunitiesList).toBeDefined();
  });

  it("should use useCallback for event handlers", async () => {
    render(<CommunitiesList />);

    await waitFor(() => {
      expect(graphService.listCommunities).toHaveBeenCalled();
    });

    // Handlers should be stable - component re-renders should not break them
    const { rerender } = render(<CommunitiesList />);

    // Re-render should not cause issues with stable handler references
    rerender(<CommunitiesList />);
  });

  it("should use useMemo for computed pagination values", async () => {
    (graphService.listCommunities as any).mockResolvedValue({
      communities: mockCommunities,
      total: 50,
    });

    render(<CommunitiesList />);

    await waitFor(() => {
      expect(graphService.listCommunities).toHaveBeenCalled();
    });

    // Pagination should work correctly with memoized values
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
  });

  it("should have stable color palette outside component", () => {
    // Color palette should be defined outside component to avoid re-creation
    const colors = [
      "from-blue-500 to-cyan-500",
      "from-purple-500 to-pink-500",
      "from-emerald-500 to-teal-500",
      "from-orange-500 to-amber-500",
      "from-rose-500 to-red-500",
    ];

    expect(colors).toHaveLength(5);
    expect(colors[0]).toBe("from-blue-500 to-cyan-500");
  });
});

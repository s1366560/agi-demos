import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "../../utils";
import { CommunitiesList } from "../../../pages/project/CommunitiesList";
import { graphService } from "../../../services/graphService";
import { useParams } from "react-router-dom";

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

import { boardLocation } from './boardLocation';
import { readDirectory } from './readDirectory';

interface GeneResponse {
  id: string;
  name: string;
}

async function boardProjection(resource: string, workspace: string, query: Record<string, string>) {
  const reply = (await window.memstack.invoke('blackboard-read', {
    workspace_id: workspace,
    resource,
    query,
  })) as { data: unknown };
  return reply.data;
}

export const geneMarketService = {
  async listGenes({
    page,
    page_size,
    search,
  }: {
    page: number;
    page_size: number;
    search?: string;
  }) {
    const ctx = await window.memstack.getContext();
    const workspace=boardLocation(ctx).id??(await readDirectory(window.memstack))[0]?.id;
    if (!workspace) throw Error('workspace_required');
    return (await boardProjection('published-genes', workspace, {
      page: String(page),
      page_size: String(page_size),
      ...(search && { search }),
    })) as { genes: GeneResponse[]; total: number };
  },
};

export const agentService = {
  async listConversations(
    _project: string,
    _status: string,
    limit: number,
    offset: number,
    _token: unknown,
    { workspaceId }: { workspaceId: string }
  ) {
    return boardProjection('board-conversations', workspaceId, {
      limit: String(limit),
      offset: String(offset),
    });
  },
};

export async function openPlanPreview() {
  await window.memstack.openPage('memstack-environments', 'sandbox-interaction');
}

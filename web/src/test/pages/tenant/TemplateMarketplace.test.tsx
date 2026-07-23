import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App } from 'antd';
import { describe, expect, it, vi } from 'vitest';

import { TemplateMarketplace } from '../../../pages/tenant/TemplateMarketplace';
import { subagentTemplateService } from '../../../services/subagentTemplateService';

import type {
  SubAgentTemplateListItem,
  SubAgentTemplateListResponse,
} from '../../../services/subagentTemplateService';

vi.mock('../../../services/subagentTemplateService', () => ({
  subagentTemplateService: {
    list: vi.fn(),
    getCategories: vi.fn(),
    install: vi.fn(),
    seed: vi.fn(),
  },
}));

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function template(id: string, category: string, displayName: string): SubAgentTemplateListItem {
  return {
    id,
    tenant_id: 'tenant-1',
    name: id,
    version: '1.0.0',
    display_name: displayName,
    description: `${displayName} description`,
    category,
    tags: [category],
    author: 'MemStack',
    is_builtin: true,
    is_published: true,
    install_count: 0,
    rating: 0,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: null,
  };
}

function listResponse(templates: SubAgentTemplateListItem[]): SubAgentTemplateListResponse {
  return {
    templates,
    total: templates.length,
    page: 1,
    page_size: 50,
  };
}

describe('TemplateMarketplace', () => {
  it('ignores stale category responses after a newer category load completes', async () => {
    const initialRequest = createDeferred<SubAgentTemplateListResponse>();
    const researchRequest = createDeferred<SubAgentTemplateListResponse>();
    const codingRequest = createDeferred<SubAgentTemplateListResponse>();
    vi.mocked(subagentTemplateService.getCategories).mockResolvedValue(['research', 'coding']);
    vi.mocked(subagentTemplateService.list)
      .mockReturnValueOnce(initialRequest.promise)
      .mockReturnValueOnce(researchRequest.promise)
      .mockReturnValueOnce(codingRequest.promise);

    render(
      <App>
        <TemplateMarketplace />
      </App>
    );

    await act(async () => {
      initialRequest.resolve(
        listResponse([
          template('research-initial', 'research', 'Research Initial'),
          template('coding-initial', 'coding', 'Coding Initial'),
        ])
      );
    });

    expect(await screen.findByText('Research Initial')).toBeInTheDocument();
    expect(screen.getByText('Coding Initial')).toBeInTheDocument();

    fireEvent.click(screen.getAllByText('research')[0]);
    await waitFor(() => {
      expect(subagentTemplateService.list).toHaveBeenCalledWith({
        category: 'research',
        search: undefined,
        page: 1,
        page_size: 12,
      });
    });

    fireEvent.click(screen.getAllByText('coding')[0]);
    await waitFor(() => {
      expect(subagentTemplateService.list).toHaveBeenCalledWith({
        category: 'coding',
        search: undefined,
        page: 1,
        page_size: 12,
      });
    });

    await act(async () => {
      codingRequest.resolve(listResponse([template('coding-current', 'coding', 'Coding Current')]));
    });

    expect(await screen.findByText('Coding Current')).toBeInTheDocument();

    await act(async () => {
      researchRequest.resolve(
        listResponse([template('research-stale', 'research', 'Research Stale')])
      );
    });

    await waitFor(() => {
      expect(screen.queryByText('Research Stale')).not.toBeInTheDocument();
      expect(screen.getByText('Coding Current')).toBeInTheDocument();
    });
  });
});

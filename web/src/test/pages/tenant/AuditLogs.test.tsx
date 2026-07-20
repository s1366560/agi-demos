import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import enUS from '../../../locales/en-US.json';
import zhCN from '../../../locales/zh-CN.json';
import { AuditLogs } from '../../../pages/tenant/AuditLogs';
import { useAuditStore } from '../../../stores/audit';
import { useTenantStore } from '../../../stores/tenant';

const mockList = vi.fn();
const mockListRuntimeHooks = vi.fn();
const mockGetRuntimeHookSummary = vi.fn();
const mockExportLogs = vi.fn();
const i18nState = vi.hoisted(() => ({ language: 'en-US' }));

function getTranslation(
  language: 'en-US' | 'zh-CN',
  key: string,
  options?: Record<string, string | number>
): string {
  const source = language === 'zh-CN' ? zhCN : enUS;
  const value = key.split('.').reduce<unknown>((current, segment) => {
    if (typeof current === 'object' && current !== null && segment in current) {
      return (current as Record<string, unknown>)[segment];
    }
    return undefined;
  }, source);

  if (typeof value !== 'string') {
    return key;
  }

  return Object.entries(options ?? {}).reduce(
    (result, [optionKey, optionValue]) =>
      result.replaceAll(`{{${optionKey}}}`, String(optionValue)),
    value
  );
}

function setMockLanguage(language: 'en-US' | 'zh-CN'): void {
  i18nState.language = language;
}

function getActionLabel(language: 'en-US' | 'zh-CN', action: string): string {
  return getTranslation(
    language,
    `tenant.auditLogs.runtimeHookSummary.actionLabels.${action.replace('runtime_hook.', '')}`
  );
}

function getExecutorLabel(language: 'en-US' | 'zh-CN', executorKind: string): string {
  return getTranslation(
    language,
    `tenant.auditLogs.runtimeHookSummary.executorLabels.${executorKind}`
  );
}

function getFamilyLabel(language: 'en-US' | 'zh-CN', hookFamily: string): string {
  return getTranslation(language, `tenant.auditLogs.runtimeHookSummary.familyLabels.${hookFamily}`);
}

function getIsolationLabel(language: 'en-US' | 'zh-CN', isolationMode: string): string {
  return getTranslation(
    language,
    `tenant.auditLogs.runtimeHookSummary.isolationLabels.${isolationMode}`
  );
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, string | number>) =>
      getTranslation(i18nState.language as 'en-US' | 'zh-CN', key, options),
    i18n: {
      changeLanguage: async (language: 'en-US' | 'zh-CN') => {
        setMockLanguage(language);
      },
      get language() {
        return i18nState.language;
      },
    },
  }),
}));

vi.mock('../../../services/auditService', () => ({
  auditService: {
    list: (...args: unknown[]) => mockList(...args),
    listRuntimeHooks: (...args: unknown[]) => mockListRuntimeHooks(...args),
    getRuntimeHookSummary: (...args: unknown[]) => mockGetRuntimeHookSummary(...args),
    exportLogs: (...args: unknown[]) => mockExportLogs(...args),
  },
}));

vi.mock('../../../stores/tenant', () => ({
  useTenantStore: vi.fn(
    (selector?: (state: { currentTenant: { id: string; name: string } | null }) => unknown) =>
      selector
        ? selector({ currentTenant: { id: 'tenant-1', name: 'Test Tenant' } })
        : { currentTenant: { id: 'tenant-1', name: 'Test Tenant' } }
  ),
}));

function mockCurrentTenant(id = 'tenant-1', name = 'Test Tenant'): void {
  vi.mocked(useTenantStore).mockImplementation(
    (selector?: (state: { currentTenant: { id: string; name: string } | null }) => unknown) =>
      selector ? selector({ currentTenant: { id, name } }) : { currentTenant: { id, name } }
  );
}

describe('AuditLogs', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setMockLanguage('en-US');
    mockCurrentTenant();
    useAuditStore.getState().reset();

    mockList.mockResolvedValue({
      items: [
        {
          id: 'audit-1',
          timestamp: '2026-04-15T08:00:00Z',
          actor: 'system',
          actor_name: null,
          action: 'tenant.updated',
          resource_type: 'tenant',
          resource_id: 'tenant-1',
          tenant_id: 'tenant-1',
          details: {},
          ip_address: null,
          user_agent: null,
        },
      ],
      total: 1,
      page: 1,
      page_size: 20,
    });

    mockListRuntimeHooks.mockResolvedValue({
      items: [
        {
          id: 'runtime-1',
          timestamp: '2026-04-15T09:00:00Z',
          actor: 'system',
          actor_name: null,
          action: 'runtime_hook.custom_execution_succeeded',
          resource_type: 'runtime_hook',
          resource_id: 'script:demo',
          tenant_id: 'tenant-1',
          details: {
            hook_name: 'before_response',
            executor_kind: 'script',
            hook_family: 'mutating',
            isolation_mode: 'sandbox',
          },
          ip_address: null,
          user_agent: null,
        },
      ],
      total: 3,
      page: 1,
      page_size: 20,
    });

    mockGetRuntimeHookSummary.mockResolvedValue({
      total: 3,
      action_counts: {
        'runtime_hook.custom_execution_succeeded': 2,
        'runtime_hook.custom_execution_failed': 1,
      },
      executor_counts: { script: 3 },
      family_counts: { mutating: 2, side_effect: 1 },
      isolation_mode_counts: { sandbox: 2, host: 1 },
      latest_timestamp: '2026-04-15T09:00:00Z',
    });

    mockExportLogs.mockResolvedValue(new Blob(['ok']));
  });

  it('loads and renders runtime hook summary when switching views', async () => {
    render(<AuditLogs />);

    await waitFor(() => {
      expect(mockList).toHaveBeenCalledWith(
        'tenant-1',
        expect.objectContaining({ page: 1, page_size: 20 })
      );
    });

    fireEvent.click(screen.getByTestId('audit-view-runtime-hooks'));

    await waitFor(() => {
      expect(mockListRuntimeHooks).toHaveBeenCalledWith(
        'tenant-1',
        expect.objectContaining({ page: 1, page_size: 20 })
      );
      expect(mockGetRuntimeHookSummary).toHaveBeenCalledWith('tenant-1', {});
    });

    expect(screen.getByTestId('runtime-hook-summary-total')).toHaveTextContent('3');
    expect(screen.getByText('Runtime Hook Summary')).toBeInTheDocument();
    expect(screen.getAllByText('Succeeded').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Script').length).toBeGreaterThan(0);
    expect(screen.getByTestId('runtime-hook-action-chart')).toBeInTheDocument();
    expect(screen.getByTestId('runtime-hook-timeline')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Details'));

    await waitFor(() => {
      expect(screen.getByText('Audit Log Detail')).toBeInTheDocument();
      expect(screen.getAllByText('Runtime Hook').length).toBeGreaterThan(0);
      expect(screen.getByText(/"executor_kind": "Script"/)).toBeInTheDocument();
    });
  });

  it('uses the route tenant id when the tenant store is still stale', async () => {
    mockCurrentTenant('tenant-store-old', 'Old Tenant');

    render(
      <MemoryRouter initialEntries={['/tenant/tenant-route-new/audit-logs']}>
        <Routes>
          <Route path="/tenant/:tenantId/audit-logs" element={<AuditLogs />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockList).toHaveBeenCalledWith(
        'tenant-route-new',
        expect.objectContaining({ page: 1, page_size: 20 })
      );
    });
    expect(mockList).not.toHaveBeenCalledWith('tenant-store-old', expect.anything());
  });

  it('passes runtime hook filters to both summary and list queries', async () => {
    render(<AuditLogs />);

    await waitFor(() => {
      expect(mockList).toHaveBeenCalled();
    });

    fireEvent.click(screen.getByTestId('audit-view-runtime-hooks'));

    await waitFor(() => {
      expect(mockListRuntimeHooks).toHaveBeenCalled();
      expect(mockGetRuntimeHookSummary).toHaveBeenCalled();
    });

    mockListRuntimeHooks.mockClear();
    mockGetRuntimeHookSummary.mockClear();

    fireEvent.change(screen.getByPlaceholderText('Filter by hook name…'), {
      target: { value: 'before_response' },
    });

    await waitFor(() => {
      expect(mockListRuntimeHooks).toHaveBeenLastCalledWith(
        'tenant-1',
        expect.objectContaining({ hook_name: 'before_response', page: 1, page_size: 20 })
      );
      expect(mockGetRuntimeHookSummary).toHaveBeenLastCalledWith(
        'tenant-1',
        expect.objectContaining({ hook_name: 'before_response' })
      );
    });
  });

  it('passes actor filters to generic audit log queries', async () => {
    render(<AuditLogs />);

    await waitFor(() => {
      expect(mockList).toHaveBeenCalledWith(
        'tenant-1',
        expect.objectContaining({ page: 1, page_size: 20 })
      );
    });

    mockList.mockClear();

    fireEvent.change(screen.getByPlaceholderText('Filter by actor…'), {
      target: { value: 'system' },
    });

    await waitFor(() => {
      expect(mockList).toHaveBeenLastCalledWith(
        'tenant-1',
        expect.objectContaining({ actor: 'system', page: 1, page_size: 20 })
      );
    });
  });

  it('clears generic audit filters and reloads the first page', async () => {
    render(<AuditLogs />);

    await waitFor(() => {
      expect(mockList).toHaveBeenCalledWith(
        'tenant-1',
        expect.objectContaining({ page: 1, page_size: 20 })
      );
    });

    fireEvent.change(screen.getByPlaceholderText('Filter by actor…'), {
      target: { value: 'system' },
    });

    await waitFor(() => {
      expect(mockList).toHaveBeenLastCalledWith(
        'tenant-1',
        expect.objectContaining({ actor: 'system' })
      );
    });

    mockList.mockClear();

    fireEvent.click(screen.getByLabelText('Clear filters'));

    await waitFor(() => {
      expect(mockList).toHaveBeenLastCalledWith(
        'tenant-1',
        expect.not.objectContaining({ actor: 'system' })
      );
      expect(mockList).toHaveBeenLastCalledWith(
        'tenant-1',
        expect.objectContaining({ page: 1, page_size: 20 })
      );
    });
  });

  it('exports runtime hook audit logs with the active hook filters', async () => {
    render(<AuditLogs />);

    await waitFor(() => {
      expect(mockList).toHaveBeenCalled();
    });

    fireEvent.click(screen.getByTestId('audit-view-runtime-hooks'));

    await waitFor(() => {
      expect(mockListRuntimeHooks).toHaveBeenCalled();
    });

    fireEvent.change(screen.getByPlaceholderText('Filter by hook name…'), {
      target: { value: 'before_response' },
    });

    await waitFor(() => {
      expect(mockGetRuntimeHookSummary).toHaveBeenLastCalledWith(
        'tenant-1',
        expect.objectContaining({ hook_name: 'before_response' })
      );
    });

    fireEvent.click(screen.getByText('Export CSV'));

    await waitFor(() => {
      expect(mockExportLogs).toHaveBeenCalledWith(
        'tenant-1',
        'csv',
        expect.objectContaining({ hook_name: 'before_response', page: 1, page_size: 20 })
      );
    });
  });

  it('rerenders localized runtime hook labels after switching language to zh-CN', async () => {
    const { rerender } = render(<AuditLogs />);

    await waitFor(() => {
      expect(mockList).toHaveBeenCalled();
    });

    fireEvent.click(screen.getByTestId('audit-view-runtime-hooks'));

    await waitFor(() => {
      expect(screen.getByText('Runtime Hook Summary')).toBeInTheDocument();
    });

    setMockLanguage('zh-CN');
    rerender(<AuditLogs />);

    await waitFor(() => {
      expect(screen.getByText('运行时 Hook 概览')).toBeInTheDocument();
      expect(screen.getAllByText('已成功').length).toBeGreaterThan(0);
      expect(screen.getAllByText('脚本').length).toBeGreaterThan(0);
      expect(screen.getAllByText('运行时 Hook').length).toBeGreaterThan(0);
    });

    fireEvent.click(screen.getByText('详情'));

    await waitFor(() => {
      expect(screen.getByText('审计日志详情')).toBeInTheDocument();
      expect(screen.getByText(/"executor_kind": "脚本"/)).toBeInTheDocument();
      expect(screen.getByText(/"hook_family": "变更型"/)).toBeInTheDocument();
      expect(screen.getByText(/"isolation_mode": "沙箱"/)).toBeInTheDocument();
    });
  });

  it.each([
    {
      action: 'runtime_hook.custom_execution_blocked',
      executor_kind: 'builtin',
      hook_family: 'observational',
      isolation_mode: 'host',
    },
    {
      action: 'runtime_hook.custom_execution_started',
      executor_kind: 'script',
      hook_family: 'mutating',
      isolation_mode: 'sandbox',
    },
    {
      action: 'runtime_hook.custom_execution_failed',
      executor_kind: 'plugin',
      hook_family: 'policy',
      isolation_mode: 'host',
    },
    {
      action: 'runtime_hook.custom_execution_succeeded',
      executor_kind: 'script',
      hook_family: 'side_effect',
      isolation_mode: 'sandbox',
    },
    {
      action: 'runtime_hook.custom_execution_requires_sandbox',
      executor_kind: 'plugin',
      hook_family: 'observational',
      isolation_mode: 'sandbox',
    },
  ])(
    'renders localized detail drawer values for $action / $executor_kind / $hook_family / $isolation_mode in %s',
    async (runtimeCase) => {
      for (const language of ['en-US', 'zh-CN'] as const) {
        setMockLanguage(language);

        const expectedAction = getActionLabel(language, runtimeCase.action);
        const expectedExecutor = getExecutorLabel(language, runtimeCase.executor_kind);
        const expectedFamily = getFamilyLabel(language, runtimeCase.hook_family);
        const expectedIsolation = getIsolationLabel(language, runtimeCase.isolation_mode);
        const expectedDetailTitle = getTranslation(language, 'tenant.auditLogs.detailTitle');
        const expectedViewDetails = getTranslation(language, 'tenant.auditLogs.viewDetails');
        const expectedActionLabel = getTranslation(language, 'tenant.auditLogs.colAction');
        const expectedResourceTypeLabel = getTranslation(
          language,
          'tenant.auditLogs.colResourceType'
        );
        const expectedResourceTypeValue = getTranslation(
          language,
          'tenant.auditLogs.runtimeHookSummary.resourceTypeLabel'
        );

        mockListRuntimeHooks.mockResolvedValueOnce({
          items: [
            {
              id: `${runtimeCase.action}-${runtimeCase.executor_kind}-${language}`,
              timestamp: '2026-04-15T09:00:00Z',
              actor: 'system',
              actor_name: null,
              action: runtimeCase.action,
              resource_type: 'runtime_hook',
              resource_id: `${runtimeCase.executor_kind}:demo`,
              tenant_id: 'tenant-1',
              details: {
                hook_name: 'before_response',
                executor_kind: runtimeCase.executor_kind,
                hook_family: runtimeCase.hook_family,
                isolation_mode: runtimeCase.isolation_mode,
              },
              ip_address: null,
              user_agent: null,
            },
          ],
          total: 1,
          page: 1,
          page_size: 20,
        });
        mockGetRuntimeHookSummary.mockResolvedValueOnce({
          total: 1,
          action_counts: { [runtimeCase.action]: 1 },
          executor_counts: { [runtimeCase.executor_kind]: 1 },
          family_counts: { [runtimeCase.hook_family]: 1 },
          isolation_mode_counts: { [runtimeCase.isolation_mode]: 1 },
          latest_timestamp: '2026-04-15T09:00:00Z',
        });

        const { unmount } = render(<AuditLogs />);

        await waitFor(() => {
          expect(mockList).toHaveBeenCalled();
        });

        fireEvent.click(screen.getByTestId('audit-view-runtime-hooks'));

        await waitFor(() => {
          expect(screen.getAllByText(expectedAction).length).toBeGreaterThan(0);
        });

        fireEvent.click(screen.getByText(expectedViewDetails));

        await waitFor(() => {
          expect(screen.getByText(expectedDetailTitle)).toBeInTheDocument();
        });

        const drawer = screen.getByRole('dialog');
        const actionSection = within(drawer).getByText(expectedActionLabel).parentElement;
        const resourceTypeSection =
          within(drawer).getByText(expectedResourceTypeLabel).parentElement;

        expect(actionSection).not.toBeNull();
        expect(resourceTypeSection).not.toBeNull();
        expect(actionSection).toHaveTextContent(expectedAction);
        expect(resourceTypeSection).toHaveTextContent(expectedResourceTypeValue);
        expect(
          within(drawer).getByText(new RegExp(`"executor_kind": "${expectedExecutor}"`))
        ).toBeInTheDocument();
        expect(
          within(drawer).getByText(
            new RegExp(`"hook_family": "${expectedFamily.replace('/', '\\/')}"`)
          )
        ).toBeInTheDocument();
        expect(
          within(drawer).getByText(new RegExp(`"isolation_mode": "${expectedIsolation}"`))
        ).toBeInTheDocument();

        unmount();
      }
    }
  );

  it('resets to page 1 before loading runtime hook view from a later page', async () => {
    mockList.mockResolvedValue({
      items: [
        {
          id: 'audit-1',
          timestamp: '2026-04-15T08:00:00Z',
          actor: 'system',
          actor_name: null,
          action: 'tenant.updated',
          resource_type: 'tenant',
          resource_id: 'tenant-1',
          tenant_id: 'tenant-1',
          details: {},
          ip_address: null,
          user_agent: null,
        },
      ],
      total: 45,
      page: 1,
      page_size: 20,
    });

    render(<AuditLogs />);

    await waitFor(() => {
      expect(mockList).toHaveBeenCalledWith(
        'tenant-1',
        expect.objectContaining({ page: 1, page_size: 20 })
      );
    });

    fireEvent.click(screen.getByText('Next'));

    await waitFor(() => {
      expect(mockList).toHaveBeenLastCalledWith(
        'tenant-1',
        expect.objectContaining({ page: 2, page_size: 20 })
      );
    });

    fireEvent.click(screen.getByTestId('audit-view-runtime-hooks'));

    await waitFor(() => {
      expect(mockListRuntimeHooks).toHaveBeenLastCalledWith(
        'tenant-1',
        expect.objectContaining({ page: 1, page_size: 20 })
      );
    });
  });

  it('renders empty state when no tenant is selected', () => {
    vi.mocked(useTenantStore).mockImplementation(((
      selector?: (state: { currentTenant: null }) => unknown
    ) => (selector ? selector({ currentTenant: null }) : { currentTenant: null })) as never);

    render(<AuditLogs />);

    expect(screen.getByText('No tenant selected')).toBeInTheDocument();
  });
});

import type { ReactNode } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DeployProgress } from '@/pages/tenant/DeployProgress';

import { App } from 'antd';

const appMessageMock = {
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
  loading: vi.fn(),
};

vi.spyOn(App, 'useApp').mockReturnValue({ message: appMessageMock } as unknown as ReturnType<
  typeof App.useApp
>);

const mocks = vi.hoisted(() => ({
  listDeploys: vi.fn().mockResolvedValue(undefined),
  createDeploy: vi.fn().mockResolvedValue({ id: 'deploy-qa' }),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (_key: string, fallback: string) => fallback }),
}));
vi.mock('@/stores/deploy', () => ({
  useDeploys: () => [],
  useCurrentDeploy: () => null,
  useDeployLoading: () => false,
  useDeploySubmitting: () => false,
  useDeployError: () => null,
  useDeployTotal: () => 0,
  useDeployActions: () => mocks,
}));
vi.mock('@/components/ui/lazyAntd', () => ({
  LazyButton: ({
    children,
    disabled,
    onClick,
  }: {
    children: ReactNode;
    disabled?: boolean;
    onClick?: () => void;
  }) => (
    <button disabled={disabled} onClick={onClick}>
      {children}
    </button>
  ),
  LazyEmpty: ({ description }: { description: ReactNode }) => <div>{description}</div>,
}));

function show(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/deploy" element={<DeployProgress />} />
        <Route path="/instances/:instanceId/deploy" element={<DeployProgress />} />
        <Route path="/deploy/:deployId" element={<div>Created</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('deployment creation context', () => {
  beforeEach(() => vi.clearAllMocks());

  it('disables tenant-level creation and explains the instance entry point', () => {
    show('/deploy');
    const action = screen.getByRole('button', { name: 'New Deploy' });
    expect(action).toBeDisabled();
    expect(screen.getByText('Open an instance to create a deployment.')).toBeVisible();
    fireEvent.click(action);
    expect(mocks.createDeploy).not.toHaveBeenCalled();
  });

  it('keeps deployment creation enabled for an explicit instance', async () => {
    show('/instances/instance-qa/deploy');
    const action = screen.getByRole('button', { name: 'New Deploy' });
    expect(action).toBeEnabled();
    fireEvent.click(action);
    expect(await screen.findByText('Created')).toBeVisible();
    expect(mocks.createDeploy).toHaveBeenCalledWith({
      instance_id: 'instance-qa',
      description: 'Manual deploy',
    });
  });
});

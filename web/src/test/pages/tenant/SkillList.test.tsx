import { Suspense } from 'react';

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SkillList } from '@/pages/tenant/SkillList';

import { fireEvent, render, screen, waitFor } from '../../utils';

const navigateMock = vi.hoisted(() => vi.fn());

const skillStore = vi.hoisted(() => ({
  skills: [],
  listSkills: vi.fn(),
  deleteSkill: vi.fn(),
  updateSkillStatus: vi.fn(),
  clearError: vi.fn(),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useLocation: () => ({ pathname: '/tenant/acme/skills' }),
    useNavigate: () => navigateMock,
  };
});

vi.mock('@/stores/skill', () => ({
  useSkillStore: () => skillStore,
  useSkillLoading: () => false,
  useSkillError: () => null,
  useActiveSkillsCount: () => 0,
  useSkillTotal: () => 0,
}));

describe('SkillList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    skillStore.listSkills.mockResolvedValue(undefined);
  });

  it('routes skill creation to chat instead of the removed manual creation page', async () => {
    render(
      <Suspense fallback={<div>Loading</div>}>
        <SkillList />
      </Suspense>
    );

    fireEvent.click(await screen.findByRole('button', { name: 'Create in chat' }));

    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith('/tenant/acme/agent-workspace', {
        state: {
          suggestedPrompt: 'Help me create a new skill.',
        },
      });
    });
    expect(navigateMock).not.toHaveBeenCalledWith('new');
  });
});

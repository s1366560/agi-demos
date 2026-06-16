import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SkillModal } from '@/components/skill/SkillModal';

import { fireEvent, render, screen, waitFor } from '../../utils';

import type { SkillResponse } from '@/types/agent';

const skillStore = vi.hoisted(() => ({
  updateSkill: vi.fn(),
  isSubmitting: false,
}));

vi.mock('@/stores/skill', () => ({
  useSkillSubmitting: () => skillStore.isSubmitting,
  useSkillStore: () => ({
    updateSkill: skillStore.updateSkill,
  }),
}));

describe('SkillModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    skillStore.updateSkill.mockResolvedValue({
      id: 'skill-1',
      name: 'pdf-processing',
    });
  });

  it('preserves omitted allowed-tools when editing unrestricted skills', async () => {
    const skill: SkillResponse = {
      id: 'skill-1',
      tenant_id: 'tenant-1',
      project_id: null,
      name: 'pdf-processing',
      description: 'Extract PDF text and tables. Use when working with PDF documents.',
      tools: ['*'],
      full_content:
        '---\nname: pdf-processing\ndescription: "Extract PDF text and tables. Use when working with PDF documents."\n---\n\n# PDF processing\n\nRead PDFs.',
      status: 'active',
      scope: 'tenant',
      is_system_skill: false,
      created_at: '2026-06-05T00:00:00Z',
      updated_at: '2026-06-05T00:00:00Z',
      metadata: {},
      agent_modes: [],
      license: null,
      compatibility: null,
      allowed_tools_raw: null,
      spec_version: '1.0',
      current_version: 1,
      version_label: null,
    };

    render(<SkillModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} skill={skill} />);

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(skillStore.updateSkill).toHaveBeenCalledWith(
        'skill-1',
        expect.objectContaining({
          tools: ['*'],
          allowed_tools_raw: null,
          full_content: expect.not.stringContaining('allowed-tools:'),
        })
      );
    });
  });

  it('submits an empty metadata object when advanced metadata is cleared', async () => {
    const skill: SkillResponse = {
      id: 'skill-1',
      tenant_id: 'tenant-1',
      project_id: null,
      name: 'pdf-processing',
      description: 'Extract PDF text and tables. Use when working with PDF documents.',
      tools: ['read_file'],
      full_content:
        '---\nname: pdf-processing\ndescription: "Extract PDF text and tables. Use when working with PDF documents."\nmetadata: {"owner":"docs"}\n---\n\n# PDF processing\n\nRead PDFs.',
      status: 'active',
      scope: 'tenant',
      is_system_skill: false,
      created_at: '2026-06-05T00:00:00Z',
      updated_at: '2026-06-05T00:00:00Z',
      metadata: { owner: 'docs' },
      agent_modes: [],
      license: null,
      compatibility: null,
      allowed_tools_raw: 'read_file',
      spec_version: '1.0',
      current_version: 1,
      version_label: null,
    };

    render(<SkillModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} skill={skill} />);

    fireEvent.click(screen.getByRole('switch'));
    fireEvent.change(await screen.findByLabelText('Metadata JSON'), {
      target: { value: '' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(skillStore.updateSkill).toHaveBeenCalledWith(
        'skill-1',
        expect.objectContaining({
          metadata: {},
          full_content: expect.not.stringContaining('metadata:'),
        })
      );
    });
  });
});

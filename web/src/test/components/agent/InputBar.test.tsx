import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { mentionService } from '@/services/mentionService';
import { skillAPI } from '@/services/skillService';

import { InputBar } from '@/components/agent/InputBar';

import type { SkillResponse } from '@/types/agent';

vi.mock('@/components/agent/FileUploader', () => ({
  useFileUpload: () => ({
    attachments: [],
    addFiles: vi.fn(),
    removeAttachment: vi.fn(),
    retryAttachment: vi.fn(),
    clearAll: vi.fn(),
  }),
}));

vi.mock('@/services/skillService', () => ({
  skillAPI: {
    list: vi.fn(),
  },
}));

vi.mock('@/services/mentionService', () => ({
  mentionService: {
    search: vi.fn(),
  },
}));

vi.mock('@/components/agent/chat/PromptTemplateLibrary', () => ({
  PromptTemplateLibrary: () => null,
}));

vi.mock('@/components/agent/chat/VoiceWaveform', () => ({
  VoiceWaveform: () => null,
}));

const mockSkill: SkillResponse = {
  id: 'skill-1',
  tenant_id: 'tenant-1',
  project_id: null,
  name: 'planner',
  description: 'Plan implementation steps',
  trigger_type: 'keyword',
  trigger_patterns: [],
  tools: [],
  prompt_template: null,
  full_content: null,
  status: 'active',
  scope: 'tenant',
  is_system_skill: false,
  success_rate: 1,
  success_count: 0,
  failure_count: 0,
  usage_count: 3,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  current_version: 1,
  version_label: null,
};

describe('InputBar autocomplete overlays', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(skillAPI.list).mockResolvedValue({
      skills: [mockSkill],
      total: 1,
    });
    vi.mocked(mentionService.search).mockResolvedValue([
      {
        id: 'entity-1',
        name: 'docs',
        type: 'entity',
      },
    ]);
  });

  it('shows slash skill dropdown when typing / query', async () => {
    render(<InputBar onSend={vi.fn()} onAbort={vi.fn()} isStreaming={false} />);

    const input = await screen.findByTestId('chat-input');
    fireEvent.change(input, { target: { value: '/pla' } });

    await waitFor(() => {
      expect(skillAPI.list).toHaveBeenCalled();
    });
    expect(await screen.findByText('/planner')).toBeInTheDocument();
    expect(input.closest('.overflow-visible')).toBeInTheDocument();
  });

  it('shows mention popover when typing @ query', async () => {
    render(
      <InputBar onSend={vi.fn()} onAbort={vi.fn()} isStreaming={false} projectId="project-1" />
    );

    const input = await screen.findByTestId('chat-input');
    fireEvent.change(input, { target: { value: '@doc', selectionStart: 4 } });

    await waitFor(() => {
      expect(mentionService.search).toHaveBeenCalledWith('doc', 'project-1');
    });
    expect(screen.getByText('agent.mentions.title')).toBeInTheDocument();
    expect(screen.getByText('docs')).toBeInTheDocument();
    expect(input.closest('.overflow-visible')).toBeInTheDocument();
  });
});

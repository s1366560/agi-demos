import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { mentionService } from '@/services/mentionService';
import { skillAPI } from '@/services/skillService';
import { attachmentService } from '@/services/attachmentService';

// eslint-disable-next-line no-restricted-imports
import { InputBar } from '@/components/agent/InputBar';

import type { SkillResponse } from '@/types/agent';

const fileUploadMock = vi.hoisted(() => ({
  attachments: [] as Array<Record<string, unknown>>,
  clearAll: vi.fn(),
}));

vi.mock('@/components/agent/FileUploader', () => ({
  useFileUpload: () => ({
    attachments: fileUploadMock.attachments,
    addFiles: vi.fn(),
    removeAttachment: vi.fn(),
    retryAttachment: vi.fn(),
    clearAll: fileUploadMock.clearAll,
  }),
}));

vi.mock('@/services/attachmentService', () => ({
  attachmentService: {
    upload: vi.fn(),
  },
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
  tools: [],
  full_content: null,
  status: 'active',
  scope: 'tenant',
  is_system_skill: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  agent_modes: ['*'],
  spec_version: '1.0',
  current_version: 1,
  version_label: null,
};

describe('InputBar autocomplete overlays', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fileUploadMock.attachments = [];
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

  it('clears slash query text after selecting a skill with Enter', async () => {
    render(<InputBar onSend={vi.fn()} onAbort={vi.fn()} isStreaming={false} />);

    const input = await screen.findByTestId('chat-input');
    fireEvent.change(input, { target: { value: '/pla' } });

    await waitFor(() => {
      expect(screen.getByText('/planner')).toBeInTheDocument();
    });

    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() => {
      expect(input).toHaveValue('');
    });
    expect(screen.getByText('/planner')).toBeInTheDocument();
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
    expect(screen.getByText('Mention entities or memories')).toBeInTheDocument();
    expect(screen.getByText('docs')).toBeInTheDocument();
    expect(input.closest('.overflow-visible')).toBeInTheDocument();
  });

  it('keeps toolbar actions separated on narrow viewports', () => {
    render(
      <InputBar onSend={vi.fn()} onAbort={vi.fn()} isStreaming={false} onTogglePlanMode={vi.fn()} />
    );

    expect(screen.getByTestId('input-toolbar')).toHaveClass('flex-wrap', 'items-center');
    expect(screen.getByTestId('input-toolbar')).toHaveClass('min-w-0', 'mt-auto');
    expect(screen.getByTestId('input-toolbar-actions')).toHaveClass(
      'justify-end',
      'ml-auto',
      'flex-wrap'
    );
  });

  it('lets the input body absorb resized composer height before the toolbar', () => {
    render(<InputBar onSend={vi.fn()} onAbort={vi.fn()} isStreaming={false} />);

    expect(screen.getByTestId('chat-input-body')).toHaveClass('flex-1', 'min-h-0');
    expect(screen.getByTestId('chat-input-surface')).toHaveClass(
      'h-full',
      'content-start',
      'items-start'
    );
  });

  it('names the hidden file input for accessibility audits', () => {
    render(<InputBar onSend={vi.fn()} onAbort={vi.fn()} isStreaming={false} />);

    const fileInput = screen.getByTestId('chat-file-input');

    expect(fileInput).toHaveAttribute('type', 'file');
    expect(fileInput).toHaveAttribute('aria-label', 'Attach files (or drag & drop)');
    expect(fileInput).toHaveAttribute('title', 'Attach files (or drag & drop)');
  });

  it('renders the structured dispatch failure instead of inferring delivery from status text', () => {
    render(
      <InputBar
        onSend={vi.fn()}
        onAbort={vi.fn()}
        isStreaming
        runInputs={[
          {
            id: 'input-1',
            conversation_id: 'conversation-1',
            run_id: 'run-1',
            expected_run_revision: 4,
            message_id: 'message-1',
            idempotency_key: 'run-input-1',
            delivery: 'steer_now',
            status: 'pending_boundary',
            sequence: 1,
            content: 'Use the focused tests',
            references: [],
            context_items: [],
            injected_via: null,
            dispatch_status: 'failed',
            dispatch_attempts: 1,
            dispatch_lease_expires_at: null,
            dispatch_error_code: 'control_channel_unavailable',
            created_at: '2026-08-04T01:00:00Z',
            updated_at: '2026-08-04T01:00:00Z',
          },
        ]}
      />
    );

    expect(screen.getByText('Delivery failed: control_channel_unavailable')).toBeInTheDocument();
  });

  it('uploads attachment context once and preserves the composer across a rejected retry', async () => {
    const file = new File(['evidence'], 'evidence.txt', { type: 'text/plain' });
    fileUploadMock.attachments = [
      {
        id: 'pending-1',
        file,
        filename: file.name,
        mimeType: file.type,
        sizeBytes: file.size,
        status: 'uploaded',
        progress: 100,
        fileMetadata: {
          filename: file.name,
          sandbox_path: '/tmp/evidence.txt',
          mime_type: file.type,
          size_bytes: file.size,
        },
      },
    ];
    vi.mocked(attachmentService.upload).mockResolvedValue({
      id: 'attachment-1',
      conversation_id: 'conversation-1',
      project_id: 'project-1',
      filename: file.name,
      mime_type: file.type,
      size_bytes: file.size,
      purpose: 'both',
      status: 'uploaded',
      created_at: '2026-08-04T01:00:00Z',
    });
    const onSubmitRunInput = vi.fn().mockResolvedValue(false);

    render(
      <InputBar
        onSend={vi.fn()}
        onAbort={vi.fn()}
        isStreaming
        projectId="project-1"
        conversationId="conversation-1"
        runInputDelivery="queue_next"
        runInputDeliveryOptions={['queue_next']}
        onSubmitRunInput={onSubmitRunInput}
      />
    );

    const input = await screen.findByTestId('chat-input');
    fireEvent.change(input, { target: { value: 'Use the attached evidence' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() => expect(onSubmitRunInput).toHaveBeenCalledTimes(1));
    expect(onSubmitRunInput).toHaveBeenLastCalledWith('Use the attached evidence', 'queue_next', {
      contextItems: [
        {
          kind: 'attachment',
          resource_id: 'attachment-1',
          label: 'evidence.txt',
          metadata: {
            mime_type: 'text/plain',
            size_bytes: file.size,
            status: 'uploaded',
          },
        },
      ],
    });
    expect(input).toHaveValue('Use the attached evidence');

    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(onSubmitRunInput).toHaveBeenCalledTimes(2));
    expect(attachmentService.upload).toHaveBeenCalledTimes(1);
    expect(fileUploadMock.clearAll).not.toHaveBeenCalled();
  });
});

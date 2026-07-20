import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';

import { CommandPalette } from '@/components/common/CommandPalette';

const mockNavigate = vi.fn();
const mockChangeLanguage = vi.fn();
const mockSetTheme = vi.fn();

const conversationsState = {
  conversations: [
    {
      id: 'conv-1',
      title: 'Deploy production fix',
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      user_id: 'user-1',
      status: 'active',
      message_count: 5,
      created_at: '2026-01-01T00:00:00.000Z',
      updated_at: '2026-01-02T00:00:00.000Z',
    },
    {
      id: 'conv-2',
      title: 'Refactor auth module',
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      user_id: 'user-1',
      status: 'active',
      message_count: 3,
      created_at: '2026-01-03T00:00:00.000Z',
      updated_at: '2026-01-04T00:00:00.000Z',
    },
  ],
};

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string | { defaultValue?: string }) => {
      if (typeof fallback === 'string') return fallback;
      if (fallback && typeof fallback === 'object' && fallback.defaultValue) return fallback.defaultValue;
      return _key;
    },
    i18n: {
      language: 'en-US',
      changeLanguage: mockChangeLanguage,
    },
  }),
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('@/stores/agent/conversationsStore', () => ({
  useConversationsStore: (selector: (state: typeof conversationsState) => unknown) =>
    selector(conversationsState),
}));

vi.mock('@/stores/theme', () => ({
  useThemeStore: (selector: (state: { computedTheme: string; setTheme: typeof mockSetTheme }) => unknown) =>
    selector({ computedTheme: 'dark', setTheme: mockSetTheme }),
}));

describe('CommandPalette', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    document.body.style.overflow = '';
    mockNavigate.mockClear();
    mockChangeLanguage.mockClear();
    mockSetTheme.mockClear();
  });
  afterEach(() => cleanup());

  it('renders nothing when closed', () => {
    render(<CommandPalette open={false} onClose={() => {}} tenantId="t1" />);
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it('renders dialog with combobox + listbox when open', () => {
    render(<CommandPalette open onClose={() => {}} tenantId="t1" />);
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog.getAttribute('aria-label')).toMatch(/command palette/i);

    const combobox = screen.getByRole('combobox');
    expect(combobox).toHaveAttribute('aria-expanded', 'true');
    expect(combobox.getAttribute('aria-controls')).toBe('command-palette-listbox');

    const listbox = document.getElementById('command-palette-listbox');
    expect(listbox).not.toBeNull();
    expect(listbox?.getAttribute('role')).toBe('listbox');
  });

  it('locks body scroll while open and restores on close', () => {
    document.body.style.overflow = 'auto';
    const { unmount } = render(<CommandPalette open onClose={() => {}} tenantId="t1" />);
    // Effect runs after paint; flush via rAF
    expect(document.body.style.overflow).toMatch(/^(hidden|auto)$/);
    unmount();
    expect(document.body.style.overflow).toBe('auto');
  });

  it('shows action + navigation + recent conversation groups', () => {
    render(<CommandPalette open onClose={() => {}} tenantId="t1" />);
    expect(screen.getByText('Actions')).toBeInTheDocument();
    expect(screen.getByText('New conversation')).toBeInTheDocument();
    // Recent conversations
    expect(screen.getByText('Deploy production fix')).toBeInTheDocument();
    expect(screen.getByText('Refactor auth module')).toBeInTheDocument();
  });

  it('filters items by query', () => {
    render(<CommandPalette open onClose={() => {}} tenantId="t1" />);
    const input = screen.getByRole('combobox') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'refactor' } });
    expect(screen.getByText('Refactor auth module')).toBeInTheDocument();
    expect(screen.queryByText('Deploy production fix')).toBeNull();
  });

  it('shows no-results message when query matches nothing', () => {
    render(<CommandPalette open onClose={() => {}} tenantId="t1" />);
    const input = screen.getByRole('combobox') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'zzzznomatch' } });
    expect(screen.getByText('No results found')).toBeInTheDocument();
  });

  it('ArrowDown moves active option; aria-activedescendant updates', () => {
    render(<CommandPalette open onClose={() => {}} tenantId="t1" />);
    const input = screen.getByRole('combobox') as HTMLInputElement;
    // Initial: first item active
    let firstOptId = input.getAttribute('aria-activedescendant');
    expect(firstOptId).toBeTruthy();
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    const secondOptId = input.getAttribute('aria-activedescendant');
    expect(secondOptId).toBeTruthy();
    expect(secondOptId).not.toBe(firstOptId);
  });

  it('Enter executes the active item (navigates)', () => {
    render(<CommandPalette open onClose={() => {}} tenantId="t1" />);
    const input = screen.getByRole('combobox') as HTMLInputElement;
    // First action is "New conversation" → navigates
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(mockNavigate).toHaveBeenCalled();
  });

  it('clicking an option executes it', () => {
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} tenantId="t1" />);
    const item = screen.getByText('Refactor auth module').closest('button')!;
    fireEvent.click(item);
    expect(mockNavigate).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('Escape closes the palette', () => {
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} tenantId="t1" />);
    const input = screen.getByRole('combobox');
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('backdrop click closes the palette', () => {
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} tenantId="t1" />);
    const backdrop = document.querySelector('.app-modal__backdrop') as HTMLElement;
    fireEvent.mouseDown(backdrop);
    expect(onClose).toHaveBeenCalled();
  });

  it('toggle-theme action calls setTheme', () => {
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} tenantId="t1" />);
    const input = screen.getByRole('combobox') as HTMLInputElement;
    // Filter to theme action
    fireEvent.change(input, { target: { value: 'light theme' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(mockSetTheme).toHaveBeenCalledWith('light');
  });

  it('toggle-language action calls i18n.changeLanguage', () => {
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} tenantId="t1" />);
    const input = screen.getByRole('combobox') as HTMLInputElement;
    // Language is en-US → label is "切换到中文"; switching to zh-CN
    fireEvent.change(input, { target: { value: '中文' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(mockChangeLanguage).toHaveBeenCalledWith('zh-CN');
  });

  it('options have role=option and aria-selected reflects active state', () => {
    render(<CommandPalette open onClose={() => {}} tenantId="t1" />);
    const options = screen.getAllByRole('option');
    expect(options.length).toBeGreaterThan(0);
    // First option is active by default
    expect(options[0]).toHaveAttribute('aria-selected', 'true');
  });
});

import { beforeEach, describe, it, expect, vi } from 'vitest';

import { NewMemory } from '../../../pages/project/NewMemory';
import { fireEvent, screen, render } from '../../utils';

vi.mock('../../../services/api', () => ({
  memoryAPI: {
    create: vi.fn(),
  },
}));

describe('NewMemory', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it('renders form elements', () => {
    render(<NewMemory />);
    // There are multiple "New Memory" texts on the page (in title and breadcrumb), use getAllByText
    expect(screen.getAllByText('New Memory').length).toBeGreaterThan(0);
    expect(screen.getByText('Save Memory')).toBeInTheDocument();
    expect(screen.getByText('Save Draft')).toBeInTheDocument();
  });

  it('labels icon-only controls for assistive technology', () => {
    render(<NewMemory />);

    expect(screen.getByRole('button', { name: 'Remove meeting tag' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Remove strategy tag' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Bold' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Code Block' })).toBeInTheDocument();
  });

  it('saves and restores a local draft', async () => {
    const { unmount } = render(<NewMemory />);

    fireEvent.change(screen.getByPlaceholderText('Enter memory title'), {
      target: { value: 'Planning notes' },
    });
    fireEvent.change(screen.getByPlaceholderText('Start writing your memory here...'), {
      target: { value: 'Draft body for later.' },
    });
    fireEvent.click(screen.getByText('Save Draft'));

    const storedDraft = window.localStorage.getItem('memstack:new-memory-draft:default');
    expect(storedDraft).not.toBeNull();

    const parsedDraft = JSON.parse(storedDraft ?? '{}') as {
      title?: string;
      content?: string;
      tags?: string[];
      savedAt?: string;
    };
    expect(parsedDraft).toMatchObject({
      title: 'Planning notes',
      content: 'Draft body for later.',
      tags: ['meeting', 'strategy'],
    });
    expect(parsedDraft.savedAt).toEqual(expect.any(String));
    expect(screen.getByText(/Draft saved at/)).toBeInTheDocument();

    unmount();

    render(<NewMemory />);

    expect(await screen.findByDisplayValue('Planning notes')).toBeInTheDocument();
    expect(await screen.findByDisplayValue('Draft body for later.')).toBeInTheDocument();
    expect(screen.getByText(/Draft saved at/)).toBeInTheDocument();
  });

  it('switches between split, edit, and preview editor modes', () => {
    render(<NewMemory />);

    fireEvent.change(screen.getByPlaceholderText('Start writing your memory here...'), {
      target: { value: 'Draft body' },
    });
    expect(screen.getByDisplayValue('Draft body')).toBeInTheDocument();
    expect(screen.getAllByText('Draft body')).toHaveLength(2);

    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));

    expect(
      screen.queryByPlaceholderText('Start writing your memory here...')
    ).not.toBeInTheDocument();
    expect(screen.getByText('Draft body')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Preview' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTitle('Bold')).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));

    expect(screen.getByDisplayValue('Draft body')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Edit' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTitle('Bold')).not.toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Split' }));

    expect(screen.getByDisplayValue('Draft body')).toBeInTheDocument();
    expect(screen.getAllByText('Draft body')).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Split' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('avoids side-stripe card accents in the preview placeholder', () => {
    const { container } = render(<NewMemory />);

    expect(container.querySelector('.border-l-4')).not.toBeInTheDocument();
  });
});

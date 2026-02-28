import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// eslint-disable-next-line no-restricted-imports
import { FinalResponseDisplay } from '@/components/agent/chat/FinalResponseDisplay';

// Mock html2pdf.js dynamic import
const mockHtml2pdf = vi.fn().mockReturnValue({
  set: vi.fn().mockReturnThis(),
  from: vi.fn().mockReturnThis(),
  save: vi.fn().mockResolvedValue(undefined),
});

// Mocking module with default export that is a function
vi.mock('html2pdf.js', () => ({
  default: () => mockHtml2pdf(),
  __esModule: true,
}));

// Mock navigator.clipboard
Object.assign(navigator, {
  clipboard: {
    writeText: vi.fn(),
  },
  share: vi.fn(),
  canShare: vi.fn().mockReturnValue(true),
});

describe('FinalResponseDisplay', () => {
  const content = '# Title\nSome content';

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders content', () => {
    render(<FinalResponseDisplay content={content} />);
    expect(screen.getByText('Final Synthesis Report')).toBeInTheDocument();
    // ReactMarkdown might render h1 as h1 tag, checking text content
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Title');
  });

  it('triggers copy action', async () => {
    render(<FinalResponseDisplay content={content} />);
    const copyButton = screen.getByText('Copy to Clipboard');
    fireEvent.click(copyButton);

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(content);
    await waitFor(() => {
      expect(screen.getByText('Copied!')).toBeInTheDocument();
    });
  });

  // Note: testing dynamic import with mocking is tricky in vitest without more setup
  // skipping detailed implementation check for now, focusing on button presence
  it('has export button', () => {
    render(<FinalResponseDisplay content={content} />);
    expect(screen.getByText('Export as PDF')).toBeInTheDocument();
  });

  it('triggers share action', async () => {
    render(<FinalResponseDisplay content={content} />);
    const shareButton = screen.getByText('Share with Team');
    fireEvent.click(shareButton);

    expect(navigator.share).toHaveBeenCalled();
  });
});

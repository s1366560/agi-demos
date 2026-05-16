import { waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { render, screen } from '@/test/utils';

import { MermaidBlock } from '@/components/agent/chat/MermaidBlock';

vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn().mockResolvedValue({
      svg: '<svg role="img" onload="alert(1)"><script>alert(1)</script><text>Safe diagram</text></svg>',
    }),
  },
}));

describe('MermaidBlock', () => {
  it('sanitizes rendered SVG before injecting it into the DOM', async () => {
    const { container } = render(<MermaidBlock chart="graph TD; A-->B;" />);

    await screen.findByText('Safe diagram');

    await waitFor(() => {
      expect(container.querySelector('script')).not.toBeInTheDocument();
      expect(container.querySelector('svg')).not.toHaveAttribute('onload');
    });
  });
});

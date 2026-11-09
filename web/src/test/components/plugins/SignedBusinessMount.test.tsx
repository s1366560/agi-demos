import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SignedBusinessMount } from '@/components/plugins/SignedBusinessMount';

const bytes = new TextEncoder().encode(
  JSON.stringify({
    schema: 'memstack.slot-ui/1',
    title: 'Notes',
    actions: [{ id: 'save', label: 'Save note' }],
  })
);

async function digest(value: Uint8Array): Promise<string> {
  const copy = new ArrayBuffer(value.byteLength);
  new Uint8Array(copy).set(value);
  const hashed = await crypto.subtle.digest('SHA-256', copy);
  return `sha256:${[...new Uint8Array(hashed)].map((item) => item.toString(16).padStart(2, '0')).join('')}`;
}

describe('SignedBusinessMount', () => {
  it('shows a verified document and removes it when the package is cleared', async () => {
    const { rerender } = render(
      <SignedBusinessMount
        document={{
          moduleRef: 'signed:sample.notes/tool-result',
          digest: await digest(bytes),
          source: 'bundle://sample.notes/ui.json',
          bytes,
        }}
      />
    );
    expect(await screen.findByTestId('signed-business-slot')).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByTestId('signed-business-slot').getAttribute('srcdoc')).toContain('Notes');
    });
    rerender(<SignedBusinessMount document={null} />);
    await waitFor(() => {
      expect(screen.queryByTestId('signed-business-slot')).toBeNull();
    });
  });
});

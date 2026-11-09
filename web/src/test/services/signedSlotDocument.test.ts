import { describe, expect, it } from 'vitest';
import { createVerifiedSignedSlotDocumentV2 } from '@agistack/plugin-slots';

const bytes = new TextEncoder().encode(
  JSON.stringify({
    schema: 'memstack.slot-ui/1',
    title: 'Notes',
    actions: [{ id: 'save', label: 'Save note' }],
  })
);

async function digest(value: Uint8Array): Promise<string> {
  const hashed = await crypto.subtle.digest('SHA-256', value);
  const hex = [...new Uint8Array(hashed)].map((item) => item.toString(16).padStart(2, '0')).join('');
  return `sha256:${hex}`;
}

describe('signed slot documents', () => {
  it('renders only digest-matched bytes for an allowed source and plane', async () => {
    const document = await createVerifiedSignedSlotDocumentV2(
      {
        moduleRef: 'signed:sample.notes/tool-result',
        digest: await digest(bytes),
        source: 'bundle://sample.notes/ui.json',
        target: 'web',
        bytes,
      },
      'nonce-1'
    );
    expect(document).toContain('Save note');
    expect(document).toContain("script-src 'nonce-nonce-1'");
    expect(
      await createVerifiedSignedSlotDocumentV2(
        {
          moduleRef: 'signed:sample.notes/tool-result',
          digest: 'sha256:' + 'ab'.repeat(32),
          source: 'bundle://sample.notes/ui.json',
          target: 'desktop-renderer',
          bytes,
        },
        'nonce-1'
      )
    ).toBeNull();
    expect(
      await createVerifiedSignedSlotDocumentV2(
        {
          moduleRef: 'builtin:web-slot-tool-result',
          digest: await digest(bytes),
          source: 'https://evil.example/ui.json',
          target: 'web',
          bytes,
        },
        'nonce-1'
      )
    ).toBeNull();
  });
});

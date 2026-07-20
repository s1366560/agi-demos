import { describe, expect, it, vi } from 'vitest';

import { AssignProviderModal } from '../../../components/provider/AssignProviderModal';
import { ProviderSelectorModal } from '../../../components/provider/ProviderSelectorModal';
import type { ProviderConfig } from '../../../types/memory';
import { fireEvent, render } from '../../utils';

vi.mock('../../../services/api', () => ({
  providerAPI: {
    assignToTenant: vi.fn(),
  },
}));

const provider: ProviderConfig = {
  id: 'provider-1',
  name: 'OpenAI',
  provider_type: 'openai',
  config: {},
  is_active: true,
  is_enabled: true,
  is_default: false,
  api_key_masked: 'sk-...',
  allowed_models: [],
  blocked_models: [],
  created_at: '2026-05-16T00:00:00Z',
  updated_at: '2026-05-16T00:00:00Z',
};

describe('provider modal keyboard behavior', () => {
  it('closes the provider selector on Escape', () => {
    const onClose = vi.fn();
    render(
      <ProviderSelectorModal isOpen onClose={onClose} onSelect={vi.fn()} providers={[provider]} />
    );

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('closes the provider assignment modal on Escape', () => {
    const onClose = vi.fn();
    render(
      <AssignProviderModal
        isOpen
        onClose={onClose}
        onSuccess={vi.fn()}
        provider={provider}
        tenantId="tenant-1"
      />
    );

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

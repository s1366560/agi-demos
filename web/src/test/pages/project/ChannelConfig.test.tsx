import { describe, expect, it } from 'vitest';

import {
  getChannelConfigEditValues,
  getChannelConfigSubmitValues,
} from '@/pages/project/channelConfigSanitizers';

import type { ChannelConfig } from '@/types/channel';

const SECRET_UNCHANGED_SENTINEL = '__MEMSTACK_SECRET_UNCHANGED__';

const channelConfig = (overrides: Partial<ChannelConfig> = {}): ChannelConfig => ({
  allow_from: undefined,
  app_id: 'cli_test',
  channel_type: 'feishu',
  connection_mode: 'websocket',
  created_at: '2026-06-17T00:00:00Z',
  description: undefined,
  dm_policy: 'open',
  domain: 'feishu',
  enabled: true,
  extra_settings: undefined,
  group_allow_from: undefined,
  group_policy: 'open',
  id: 'cfg-1',
  last_error: undefined,
  name: 'Feishu',
  project_id: 'project-1',
  rate_limit_per_minute: 60,
  status: 'disconnected',
  updated_at: undefined,
  webhook_path: undefined,
  webhook_port: undefined,
  webhook_url: undefined,
  ...overrides,
});

describe('ChannelConfig sanitizers', () => {
  it('removes secret sentinels from edit form initial values', () => {
    const values = getChannelConfigEditValues(
      channelConfig({
        extra_settings: {
          api_key: SECRET_UNCHANGED_SENTINEL,
          mode: 'safe',
        },
      })
    );

    expect(values.app_secret).toBeUndefined();
    expect(values.encrypt_key).toBeUndefined();
    expect(values.verification_token).toBeUndefined();
    expect(values.extra_settings).toEqual({ mode: 'safe' });
  });

  it('omits blank schema secret fields from edit payloads', () => {
    const payload = getChannelConfigSubmitValues(
      {
        app_secret: '',
        channel_type: 'feishu',
        extra_settings: {
          api_key: '',
          mode: 'fast',
          optional_blank: '',
          previous: SECRET_UNCHANGED_SENTINEL,
        },
        name: 'Feishu',
      },
      {
        editingConfig: channelConfig(),
        schemaSecretPaths: ['app_secret', 'api_key'],
        schemaSupported: true,
      }
    );

    expect(payload).toEqual({
      channel_type: 'feishu',
      extra_settings: { mode: 'fast', optional_blank: '' },
      name: 'Feishu',
    });
  });

  it('omits blank legacy secret fields from edit payloads', () => {
    const payload = getChannelConfigSubmitValues(
      {
        app_secret: '',
        domain: 'lark',
        encrypt_key: '',
        name: 'Feishu',
        verification_token: '',
      },
      {
        editingConfig: channelConfig(),
        schemaSupported: false,
      }
    );

    expect(payload).toEqual({
      domain: 'lark',
      name: 'Feishu',
    });
  });
});

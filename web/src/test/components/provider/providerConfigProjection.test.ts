import { describe, expect, it } from 'vitest';

import {
  projectSafeEmbeddingConfig,
  projectSafeProviderConfig,
} from '../../../components/provider/providerConfigProjection';

describe('providerConfigProjection', () => {
  it('keeps only supported public provider configuration', () => {
    expect(
      projectSafeProviderConfig({
        temperature: 0.2,
        max_tokens: 4096,
        timeout: 60,
        region: 'us-east-1',
        retries: { max_attempts: 3, secret: 'do-not-send' },
        transport: { request_timeout_seconds: 120, api_key: 'do-not-send' },
        rtc_app_key: 'do-not-send',
        volc_ak: 'do-not-send',
        volc_sk: 'do-not-send',
        speech_access_token: 'do-not-send',
        provider_options: { token: 'do-not-send' },
        unknown: 'do-not-send',
      })
    ).toEqual({
      temperature: 0.2,
      max_tokens: 4096,
      timeout: 60,
      region: 'us-east-1',
      retries: { max_attempts: 3 },
      transport: { request_timeout_seconds: 120 },
    });
  });

  it('drops embedding provider options and other unknown fields', () => {
    expect(
      projectSafeEmbeddingConfig({
        model: ' text-embedding-3-small ',
        dimensions: 1536,
        timeout: 30,
        encoding_format: 'float',
        user: ' end-user ',
        provider_options: {
          batch_size: 32,
          input_type: 'search_document',
          truncate: 'END',
          api_key: 'do-not-send',
        },
        speech_access_token: 'do-not-send',
      })
    ).toEqual({
      model: 'text-embedding-3-small',
      dimensions: 1536,
      timeout: 30,
      encoding_format: 'float',
      user: 'end-user',
      provider_options: {
        batch_size: 32,
        input_type: 'search_document',
        truncate: 'END',
      },
    });
  });
});

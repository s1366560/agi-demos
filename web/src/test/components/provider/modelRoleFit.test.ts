import { describe, expect, it } from 'vitest';

import { assessModelRole, preferredListedModel } from '../../../components/provider/modelRoleFit';

describe('assessModelRole', () => {
  it('lets an unknown model id fill chat roles and explains the assumption', () => {
    expect(assessModelRole('primary', { capabilities: [], known: false })).toEqual({
      supported: true,
      reason: 'unknown_assumed_chat',
    });
    expect(assessModelRole('embedding', { capabilities: [], known: false })).toEqual({
      supported: false,
      reason: 'embedding_capability_required',
    });
  });

  it('rejects an embedding model as the primary chat model', () => {
    expect(assessModelRole('primary', { capabilities: ['embedding'], known: true })).toEqual({
      supported: false,
      reason: 'not_a_chat_model',
    });
  });

  it('requires an explicit audio declaration instead of inferring it from the name', () => {
    expect(
      assessModelRole('voice', {
        capabilities: ['chat'],
        known: true,
        audioDeclarationAllowed: true,
      })
    ).toEqual({ supported: false, reason: 'audio_input_not_declared' });
    expect(
      assessModelRole('voice', {
        capabilities: ['chat'],
        known: true,
        audioDeclared: true,
        audioDeclarationAllowed: true,
      }).supported
    ).toBe(true);
  });

  it('keeps a deprecated chat model selectable and marked', () => {
    expect(
      assessModelRole('fast', { capabilities: ['chat'], known: true, deprecated: true })
    ).toEqual({ supported: true, reason: 'deprecated' });
  });
});

describe('preferredListedModel', () => {
  it('uses the catalog default when that id is offered', () => {
    expect(preferredListedModel(['gpt-6-luna', 'gpt-6-astra'], 'gpt-6-astra')).toBe('gpt-6-astra');
  });

  it('skips the excluded primary model', () => {
    expect(preferredListedModel(['gpt-6-astra', 'gpt-6-luna'], 'missing', 'gpt-6-astra')).toBe(
      'gpt-6-luna'
    );
  });
});

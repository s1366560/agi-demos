import { describe, expect, it } from 'vitest';

import { parseInstanceJsonObject } from '../../../pages/tenant/utils/createInstanceUtils';

describe('CreateInstance helpers', () => {
  it('parses JSON object text fields', () => {
    expect(parseInstanceJsonObject('{"KEY":"value"}')).toEqual({ KEY: 'value' });
  });

  it('rejects invalid JSON object text fields', () => {
    expect(() => parseInstanceJsonObject('not json')).toThrow('Expected a JSON object');
    expect(() => parseInstanceJsonObject('["value"]')).toThrow('Expected a JSON object');
  });
});

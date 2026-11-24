import { describe, expect, it } from 'vitest';
import { compatibilityUrl } from '../../fullHost/compatibility';

const deepLink = {
  pathname: '/tenant/acme/legacy',
  search: '?projectId=sales&view=full',
  hash: '#selected',
};
describe('the separate compatibility workbench', () => {
  it('preserves bookmarks when a local user chooses the old UI', () => {
    expect(compatibilityUrl(deepLink, new URL('http://localhost:3000'))).toBe(
      'http://localhost:3001/tenant/acme/legacy?projectId=sales&view=full#selected'
    );
  });
  it('requires an explicit deployment origin outside loopback', () => {
    const host = new URL('https://work.example');
    expect(compatibilityUrl(deepLink, host)).toBeNull();
    expect(compatibilityUrl(deepLink, host, 'https://old.example')).toBe(
      'https://old.example/tenant/acme/legacy?projectId=sales&view=full#selected'
    );
    for (const invalid of [
      host.origin,
      'https://user@example.org',
      'https://old.example/arbitrary',
      'javascript:alert(1)',
    ])
      expect(compatibilityUrl(deepLink, host, invalid)).toBeNull();
  });
});

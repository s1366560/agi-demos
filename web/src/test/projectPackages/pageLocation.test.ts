import { describe, expect, it } from 'vitest';

import {
  pageSearch,
  scopedPageLocation,
  splitPageLocation,
} from '../../../../agi-stack/packages/plugin-slots/src/pageLocation';

describe('signed business page addresses', () => {
  it('keeps filters, repeated keys and anchors while binding the real project', () => {
    const path = '/graph?filter=a&filter=b&project=wrong#node';
    expect(scopedPageLocation(path, { project: 'p' })).toEqual({
      pathname: '/graph', search: 'filter=a&filter=b&project=p', hash: '#node',
    });
    expect(pageSearch('?filter=a&filter=b&access_token=secret&unused=x', false, ['filter']))
      .toBe('?filter=a&filter=b');
    expect(() => pageSearch('?%70roject=other', true)).toThrow('page_navigation_denied');
  });
  it('preserves the raw path for authorization and treats query characters in fragments as data', () => {
    expect(splitPageLocation('/boards/../login#a?x')).toEqual({
      pathname: '/boards/../login', hash: '#a?x', search: '',
    });
  });
});

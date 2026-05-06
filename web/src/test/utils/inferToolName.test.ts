import { describe, expect, it } from 'vitest';

import { inferToolName, isInferredToolName } from '@/utils/inferToolName';

describe('inferToolName', () => {
  it('keeps non-placeholder names as-is', () => {
    expect(inferToolName('read_file', { file_path: '/x' })).toBe('read_file');
    expect(inferToolName('custom_tool', {})).toBe('custom_tool');
  });

  it('infers codebase-retrieval from information_request', () => {
    expect(inferToolName('unknown', { information_request: 'how does X work' })).toBe(
      'codebase-retrieval',
    );
  });

  it('infers grep_search from pattern + isRegexp', () => {
    expect(inferToolName('other', { pattern: 'foo', isRegexp: true })).toBe('grep_search');
  });

  it('infers read_file from file_path-only', () => {
    expect(inferToolName('', { file_path: '/x' })).toBe('read_file');
  });

  it('infers write_file from file_path + content', () => {
    expect(inferToolName('tool', { file_path: '/x', content: 'y' })).toBe('write_file');
  });

  it('infers replace_string_in_file from edit shape', () => {
    expect(
      inferToolName('unknown', { filePath: '/x', oldString: 'a', newString: 'b' }),
    ).toBe('replace_string_in_file');
  });

  it('infers run_in_terminal from command + mode', () => {
    expect(inferToolName('unknown', { command: 'ls', mode: 'sync' })).toBe('run_in_terminal');
  });

  it('returns "unknown" when input is empty and name is placeholder', () => {
    expect(inferToolName('unknown', null)).toBe('unknown');
    expect(inferToolName('', undefined)).toBe('unknown');
    expect(inferToolName('other', [])).toBe('other');
  });

  it('isInferredToolName flags inferred renames only', () => {
    expect(isInferredToolName('unknown', { file_path: '/x' })).toBe(true);
    expect(isInferredToolName('read_file', { file_path: '/x' })).toBe(false);
  });
});

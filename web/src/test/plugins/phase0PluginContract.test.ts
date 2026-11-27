import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { jsonSchemaValidationIssueV2 } from '../../../../agi-stack/packages/plugin-runtime/src/schema';
import { npmResourcePath } from '../../../../agi-stack/packages/plugin-marketplace-ui/src/pluginMarketTypes';
import { SLOT_PORT_MESSAGE_SOURCE_V2 } from '../../../../agi-stack/packages/plugin-slots/src/portProtocol';
import { SLOT_MESSAGE_SOURCE } from '../../../../agi-stack/packages/plugin-slots/src/protocol';
import { routeMatchPaths } from '../../../../agi-stack/packages/plugin-slots/src/pageLocation';
import { richPageContentSecurityPolicy } from '../../../../agi-stack/packages/plugin-slots/src/richPage';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../../..');

describe('phase 0 plugin contracts', () => {
  it('pins the inner rich page network and data URL policy', () => {
    const policy = richPageContentSecurityPolicy('data:');
    expect(policy).toContain("default-src 'none'");
    expect(policy).toContain("connect-src 'none'");
    expect(policy).toContain('font-src data:');
    expect(policy).toContain('img-src data:');
    expect(policy).toContain('worker-src data:');
    expect(richPageContentSecurityPolicy("'none'")).toContain("worker-src 'none'");
    const outer = readFileSync(
      resolve(repoRoot, 'agi-stack/packages/plugin-slots/viteRichPageFrame.mjs'),
      'utf8',
    );
    expect(outer).toContain("connect-src 'none'");
    expect(outer).toContain("default-src 'none'");
  });

  it('matches a project route from the tenant address when the project is already named', () => {
    expect(
      routeMatchPaths('/tenant/north/agent-workspace', {
        tenantId: 'north',
        projectId: 'project-1',
      }),
    ).toEqual([
      '/tenant/north/agent-workspace',
      '/tenant/north/project/project-1/agent-workspace',
    ]);
    expect(
      routeMatchPaths('/tenant/north/billing', { tenantId: 'north', projectId: null }),
    ).toEqual(['/tenant/north/billing']);
  });

  it('uses one slot message source for frames and ports', () => {
    expect(SLOT_PORT_MESSAGE_SOURCE_V2).toBe(SLOT_MESSAGE_SOURCE);
    expect(SLOT_MESSAGE_SOURCE).toBe('memstack-plugin-slot');
  });

  it('chooses the tenant or project package API for npm detail and resolve', () => {
    expect(npmResourcePath(null, 'detail')).toBe('/api/v1/tenant-packages/npm/detail');
    expect(npmResourcePath('project-1', 'resolve')).toBe(
      '/api/v1/platform-plugins/v2/optional-business/npm/resolve',
    );
    const desktop = readFileSync(
      resolve(repoRoot, 'agi-stack/apps/desktop/src/packageHost/transport.ts'),
      'utf8',
    );
    expect(desktop).not.toContain('/api/v1/platform-plugins/v2/optional-business');
  });

  it('enforces enum, maxLength, minItems, and maxItems', () => {
    expect(jsonSchemaValidationIssueV2({ enum: ['a', 'b'] }, 'c')).toMatch(/enum/);
    expect(jsonSchemaValidationIssueV2({ type: 'string', maxLength: 2 }, 'abcd')).toMatch(
      /at most 2/,
    );
    expect(jsonSchemaValidationIssueV2({ type: 'array', minItems: 2 }, ['only'])).toMatch(
      /at least 2/,
    );
    expect(jsonSchemaValidationIssueV2({ type: 'array', maxItems: 1 }, ['a', 'b'])).toMatch(
      /at most 1/,
    );
    expect(jsonSchemaValidationIssueV2({ enum: ['a'] }, 'a')).toBeUndefined();
  });
});

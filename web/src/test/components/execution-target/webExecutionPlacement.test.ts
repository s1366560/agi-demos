import { describe, expect, it } from 'vitest';

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import {
  inheritableWebRun,
  publicDirectoryLabel,
  webCanCreateLocalRun,
  webCloudWire,
  webComposerPlacement,
} from '@/components/execution-target/webExecutionPlacement';

describe('web composer execution placement', () => {
  it('does not offer this computer and keeps a local run read-only', () => {
    const placement = webComposerPlacement({
      status: 'completed',
      execution_target: 'local',
      local_root_label: 'agi-demos',
    });
    expect(placement.offersLocal).toBe(false);
    expect(placement.readOnly).toBe(true);
    expect(placement.target).toBe('local');
    expect(placement.localRootLabel).toBe('agi-demos');
  });

  it('ignores a cancelled local run and never publishes an absolute path', () => {
    const placement = webComposerPlacement({
      status: 'cancelled',
      execution_target: 'local',
      local_root_label: '/Users/alice/src/agi-demos',
    });
    expect(placement.readOnly).toBe(false);
    expect(placement.target).toBe('cloud');
    expect(publicDirectoryLabel('/Users/alice/src/agi-demos')).toBeNull();
    const wire = webCloudWire();
    expect(wire.execution_target).toBe('cloud');
    expect(JSON.stringify(wire).includes('/Users/alice/src/agi-demos')).toBe(false);
    expect(webCanCreateLocalRun()).toBe(false);
  });

  it('inherits an earlier local run when the newest run was cancelled', () => {
    const inherited = inheritableWebRun([
      {
        status: 'cancelled',
        execution_target: 'cloud',
        updated_at: '2026-11-23T03:00:00Z',
      },
      {
        status: 'completed',
        execution_target: 'local',
        local_root_label: 'agi-demos',
        updated_at: '2026-11-23T02:00:00Z',
      },
    ]);
    expect(inherited?.execution_target).toBe('local');
    const placement = webComposerPlacement(inherited);
    expect(placement.readOnly).toBe(true);
    expect(placement.offersLocal).toBe(false);
    const source = readFileSync(
      resolve(process.cwd(), 'src/components/execution-target/webExecutionPlacement.ts'),
      'utf8',
    );
    expect(source.includes("execution_target: 'cloud'")).toBe(true);
    expect(source.includes('/local-runs')).toBe(false);
  });
});

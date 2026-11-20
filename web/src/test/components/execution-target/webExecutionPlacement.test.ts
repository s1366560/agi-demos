import { describe, expect, it } from 'vitest';

import {
  publicDirectoryLabel,
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
  });
});

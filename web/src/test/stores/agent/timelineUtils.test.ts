/** Permission outcome and explicit automatic-approval presentation tests. */

import { describe, it, expect } from 'vitest';

import {
  filterAutomaticPermissionEvents,
  mergeHITLResponseEvents,
  isGrantedPermissionEvent,
} from '../../../stores/agent/timelineUtils';

import type { TimelineEvent } from '../../../types/agent/timeline';

function base(overrides: Record<string, unknown>): TimelineEvent {
  return {
    id: 'evt-1',
    timestamp: '2026-09-17T00:00:00Z',
    ...overrides,
  } as TimelineEvent;
}

describe('isGrantedPermissionEvent', () => {
  it('identifies answered+granted permission_asked cards', () => {
    expect(
      isGrantedPermissionEvent(
        base({ type: 'permission_asked', requestId: 'r1', answered: true, granted: true })
      )
    ).toBe(true);
  });

  it('keeps pending permission_asked cards visible', () => {
    expect(
      isGrantedPermissionEvent(base({ type: 'permission_asked', requestId: 'r1', answered: false }))
    ).toBe(false);
    expect(isGrantedPermissionEvent(base({ type: 'permission_asked', requestId: 'r1' }))).toBe(
      false
    );
  });

  it('keeps denied cards visible in every shape', () => {
    expect(
      isGrantedPermissionEvent(
        base({ type: 'permission_asked', requestId: 'r1', answered: true, granted: false })
      )
    ).toBe(false);
    expect(
      isGrantedPermissionEvent(
        base({ type: 'permission_replied', requestId: 'r1', granted: false })
      )
    ).toBe(false);
    expect(
      isGrantedPermissionEvent(
        base({ type: 'permission_granted', requestId: 'r1', granted: false })
      )
    ).toBe(false);
  });

  it('identifies replied/granted projection cards with granted outcome', () => {
    expect(
      isGrantedPermissionEvent(base({ type: 'permission_replied', requestId: 'r1', granted: true }))
    ).toBe(true);
    expect(
      isGrantedPermissionEvent(base({ type: 'permission_granted', requestId: 'r1', granted: true }))
    ).toBe(true);
  });

  it('identifies answered+granted DB-format permission_requested cards', () => {
    expect(
      isGrantedPermissionEvent(
        base({ type: 'permission_requested', requestId: 'r1', answered: true, granted: true })
      )
    ).toBe(true);
    expect(
      isGrantedPermissionEvent(
        base({ type: 'permission_requested', requestId: 'r1', answered: false })
      )
    ).toBe(false);
  });

  it('ignores non-permission events', () => {
    expect(isGrantedPermissionEvent(base({ type: 'user_message', content: 'hi' }))).toBe(false);
    expect(isGrantedPermissionEvent(base({ type: 'clarification_asked', requestId: 'r1' }))).toBe(
      false
    );
  });
});

describe('filterAutomaticPermissionEvents', () => {
  it('hides an explicit automatic grant and its matching ask independently of current mode', () => {
    const ask = base({ id: 'ask', type: 'permission_asked', requestId: 'automatic' });
    const reply = base({
      id: 'reply',
      type: 'permission_replied',
      requestId: 'automatic',
      granted: true,
      autoApproved: true,
    });
    const manual = base({
      id: 'manual',
      type: 'permission_asked',
      requestId: 'manual',
      answered: true,
      granted: true,
    });
    const pending = base({
      id: 'pending',
      type: 'permission_asked',
      requestId: 'pending',
      autoApproved: true,
    });
    expect(filterAutomaticPermissionEvents([ask, reply, manual, pending])).toEqual([
      manual,
      pending,
    ]);
    expect(filterAutomaticPermissionEvents(mergeHITLResponseEvents([ask, reply, manual]))).toEqual([
      manual,
    ]);
  });
  it('uses exact persisted approval IDs after reload but keeps an explicit denial visible', () => {
    const ask = base({ id: 'ask', type: 'permission_requested', requestId: 'automatic' });
    const granted = base({
      id: 'grant',
      type: 'permission_granted',
      requestId: 'automatic',
      granted: true,
    });
    expect(filterAutomaticPermissionEvents([ask, granted], ['automatic'])).toEqual([]);
    expect(filterAutomaticPermissionEvents([ask, granted], ['another-request'])).toEqual([
      ask,
      granted,
    ]);
    const denied = base({
      id: 'denied',
      type: 'permission_replied',
      requestId: 'automatic',
      granted: false,
      autoApproved: true,
    });
    expect(filterAutomaticPermissionEvents([ask, denied], ['automatic'])).toEqual([ask, denied]);
    expect(
      filterAutomaticPermissionEvents(mergeHITLResponseEvents([ask, granted]), ['automatic'])
    ).toEqual([]);
  });
});

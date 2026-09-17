/**
 * Unit tests for isGrantedPermissionEvent.
 *
 * Feature: full-access permission mode keeps auto-approved (granted)
 * permission cards out of the message area. The classifier must hide granted
 * cards in every wire shape (live + DB projection) while keeping pending and
 * denied cards visible.
 */

import { describe, it, expect } from 'vitest';

import { isGrantedPermissionEvent } from '../../../stores/agent/timelineUtils';

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
      isGrantedPermissionEvent(
        base({ type: 'permission_asked', requestId: 'r1', answered: false })
      )
    ).toBe(false);
    expect(
      isGrantedPermissionEvent(base({ type: 'permission_asked', requestId: 'r1' }))
    ).toBe(false);
  });

  it('keeps denied cards visible in every shape', () => {
    expect(
      isGrantedPermissionEvent(
        base({ type: 'permission_asked', requestId: 'r1', answered: true, granted: false })
      )
    ).toBe(false);
    expect(
      isGrantedPermissionEvent(base({ type: 'permission_replied', requestId: 'r1', granted: false }))
    ).toBe(false);
    expect(
      isGrantedPermissionEvent(base({ type: 'permission_granted', requestId: 'r1', granted: false }))
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
    expect(
      isGrantedPermissionEvent(base({ type: 'clarification_asked', requestId: 'r1' }))
    ).toBe(false);
  });
});

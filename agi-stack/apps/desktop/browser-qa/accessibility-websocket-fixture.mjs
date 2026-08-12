const ACCESSIBILITY_WEBSOCKET_STATES = new Set([
  'baseline',
  'loading',
  'empty',
  'forbidden',
  'error',
  'conflict',
]);

export function createAccessibilityWebSocketFixture(scope) {
  const authorityScope = Object.freeze({
    tenantId: requireIdentifier(
      scope?.tenantId,
      'accessibility_websocket_tenant_scope_required',
    ),
    projectId: requireIdentifier(
      scope?.projectId,
      'accessibility_websocket_project_scope_required',
    ),
  });
  let state = 'baseline';
  let connections = 0;
  let receivedMessages = 0;
  const pendingConnections = new Set();

  return Object.freeze({
    setState(nextState) {
      if (!ACCESSIBILITY_WEBSOCKET_STATES.has(nextState)) {
        throw new Error('accessibility_websocket_state_invalid');
      }
      state = nextState;
    },
    async handle(route) {
      connections += 1;
      route.onMessage(() => {
        receivedMessages += 1;
      });
      const connectionState = state;
      if (connectionState === 'loading') {
        await new Promise((resolve) => {
          pendingConnections.add(resolve);
        });
        return;
      }
      const frame = accessibilityWebSocketStateFrame(
        connectionState,
        authorityScope,
      );
      if (frame !== null) route.send(frame);
    },
    releasePending() {
      for (const resolve of pendingConnections) resolve();
      pendingConnections.clear();
    },
    observation() {
      return Object.freeze({
        state,
        connections,
        receivedMessages,
        pendingConnections: pendingConnections.size,
      });
    },
  });
}

export function accessibilityWebSocketStateFrame(state, scope) {
  if (!ACCESSIBILITY_WEBSOCKET_STATES.has(state)) {
    throw new Error('accessibility_websocket_state_invalid');
  }
  const tenantId = requireIdentifier(
    scope?.tenantId,
    'accessibility_websocket_tenant_scope_required',
  );
  const projectId = requireIdentifier(
    scope?.projectId,
    'accessibility_websocket_project_scope_required',
  );
  if (state === 'loading' || state === 'empty') return null;
  if (state === 'baseline') {
    return JSON.stringify({
      type: 'accessibility_authority_observed',
      event_id: 'accessibility-event-1',
      tenant_id: tenantId,
      project_id: projectId,
    });
  }
  const code = {
    forbidden: 'CONVERSATION_ACCESS_DENIED',
    error: 'ACCESSIBILITY_FIXTURE_ERROR',
    conflict: 'MESSAGE_ID_CONFLICT',
  }[state];
  return JSON.stringify({
    type: 'error',
    code,
    reason_code: `accessibility_fixture_${state}`,
    tenant_id: tenantId,
    project_id: projectId,
  });
}

function requireIdentifier(value, reasonCode) {
  if (typeof value !== 'string' || value.length === 0 || value.trim() !== value) {
    throw new Error(reasonCode);
  }
  return value;
}

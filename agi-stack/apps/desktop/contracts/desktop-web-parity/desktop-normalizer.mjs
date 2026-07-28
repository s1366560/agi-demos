export function normalizeDesktopParityFixture(fixture) {
  if (fixture.kind === 'live_events') {
    return replayDesktopEvents(
      fixture.input.events.map((event) => ({
        eventType: event.type,
        messageId: event.message_id,
        payload: event.data,
      })),
    );
  }
  if (fixture.kind === 'history_replay') {
    return replayDesktopEvents(
      fixture.input.records.map((record) => ({
        eventType: record.event_type,
        messageId: record.message_id,
        payload: record.payload,
      })),
    );
  }
  if (fixture.kind === 'capability_snapshot') {
    return projectDesktopCapabilitySnapshot(fixture.input.snapshot);
  }
  if (fixture.kind === 'hitl_authority') {
    return projectDesktopHitlAuthority(fixture.input.request);
  }
  if (fixture.kind === 'workspace_surface') {
    return projectDesktopWorkspaceSurface(fixture.input.surface);
  }
  if (fixture.kind === 'artifact_content') {
    return projectDesktopArtifactContent(fixture.input.artifact);
  }
  if (fixture.kind === 'sandbox_runtime') {
    return projectDesktopSandboxRuntime(fixture.input.runtime);
  }
  if (fixture.kind === 'automation_run_receipt') {
    return projectDesktopAutomationReceipt(fixture.input.receipt);
  }
  throw new TypeError(`Unsupported Desktop parity fixture kind: ${String(fixture.kind)}`);
}

function replayDesktopEvents(events) {
  const order = [];
  const messages = {};
  for (const event of events) {
    if (event.eventType !== 'assistant_message' && event.eventType !== 'text_end') continue;
    if (!Object.hasOwn(messages, event.messageId)) order.push(event.messageId);
    const prior = messages[event.messageId];
    const text =
      typeof event.payload.content === 'string' ? event.payload.content : (prior?.text ?? '');
    messages[event.messageId] = {
      key: event.messageId,
      message_id: event.messageId,
      role: 'assistant',
      text,
      state:
        event.eventType === 'text_end' || event.payload.is_partial === false
          ? 'completed'
          : 'streaming',
    };
  }
  const timeline = order.map((messageId) => messages[messageId]);
  let activeMessageId = null;
  for (const message of timeline) {
    if (message.state === 'streaming') activeMessageId = message.message_id;
  }
  return { active_message_id: activeMessageId, timeline };
}

function projectDesktopCapabilitySnapshot(snapshot) {
  const {
    automation_run: automationRun,
    search,
    workspace_collaboration: workspaceCollaboration,
    sandbox_isolation: sandboxIsolation,
  } = snapshot.capabilities;
  return {
    mode: snapshot.mode,
    features: {
      automation_run: projectDesktopAvailability(automationRun),
      search: projectDesktopAvailability(search),
      workspace_collaboration: projectDesktopAvailability(workspaceCollaboration),
      sandbox_isolation: projectDesktopAvailability(sandboxIsolation),
    },
  };
}

function projectDesktopAvailability(capability) {
  if (typeof capability.status === 'string') {
    return {
      status: capability.status,
      available: capability.status === 'available' || capability.status === 'degraded',
      reason_code: capability.reason_code,
      service_version: capability.service_version,
      contract_version: capability.contract_version,
      minimum_contract_version: capability.minimum_contract_version,
    };
  }
  return {
    available: capability.available,
    reason_code: capability.reason_code,
  };
}

function projectDesktopHitlAuthority(request) {
  return {
    request_id: request.request_id,
    request_type: request.request_type,
    status: request.status,
    authority_revision: request.authority_revision,
    terminal_at: request.answered_at ?? request.expired_at,
    editable: request.status === 'pending',
  };
}

function projectDesktopWorkspaceSurface(surface) {
  return {
    workspace_id: surface.workspace_id,
    surface: surface.surface,
    authority: surface.authority,
    status: surface.status,
    revision: surface.revision,
    cursor: surface.cursor,
    item_count: surface.items.length,
    requires_canonical_refetch: surface.status === 'stale',
  };
}

function projectDesktopArtifactContent(artifact) {
  return {
    artifact_id: artifact.artifact_id,
    mime_type: artifact.mime_type,
    revision: artifact.revision,
    content_hash: artifact.content_hash,
    editable: artifact.editable,
    conflict_safe: artifact.expected_revision === artifact.revision,
    has_idempotency_key: artifact.idempotency_key.length > 0,
  };
}

function projectDesktopSandboxRuntime(runtime) {
  const features = {};
  for (const name of ['terminal_interactive', 'terminal_resume', 'files', 'kasm_vnc']) {
    const capability = runtime[name];
    features[name] = {
      availability: capability.availability,
      available:
        capability.availability === 'available' || capability.availability === 'degraded',
      contract_version: capability.contract_version,
      reason_code: capability.reason_code,
    };
  }
  return {
    service_version: runtime.service_version,
    contract_version: runtime.contract_version,
    features,
  };
}

function projectDesktopAutomationReceipt(receipt) {
  return {
    contract_version: receipt.contract_version,
    receipt_id: receipt.receipt_id,
    run_id: receipt.run_id,
    job_id: receipt.job_id,
    status: receipt.status,
    duplicate: receipt.duplicate,
    expected_revision: receipt.expected_revision,
    replay_safe: receipt.contract_version === 2 && receipt.idempotency_key.length > 0,
  };
}

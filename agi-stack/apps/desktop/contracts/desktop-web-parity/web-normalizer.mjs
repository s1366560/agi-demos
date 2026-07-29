const CAPABILITY_NAMES = [
  'automation_run',
  'search',
  'workspace_collaboration',
  'sandbox_isolation',
];

export function normalizeWebParityFixture(fixture) {
  switch (fixture.kind) {
    case 'live_events':
      return normalizeWebTimeline(fixture.input.events, 'data', 'type');
    case 'history_replay':
      return normalizeWebTimeline(fixture.input.records, 'payload', 'event_type');
    case 'capability_snapshot':
      return normalizeWebCapabilitySnapshot(fixture.input.snapshot);
    case 'hitl_authority':
      return normalizeWebHitlAuthority(fixture.input.request);
    case 'workspace_surface':
      return normalizeWebWorkspaceSurface(fixture.input.surface);
    case 'artifact_content':
      return normalizeWebArtifactContent(fixture.input.artifact);
    case 'sandbox_runtime':
      return normalizeWebSandboxRuntime(fixture.input.runtime);
    case 'automation_run_receipt':
      return normalizeWebAutomationReceipt(fixture.input.receipt);
    default:
      throw new TypeError(`Unsupported Web parity fixture kind: ${String(fixture.kind)}`);
  }
}

function normalizeWebTimeline(entries, payloadKey, eventTypeKey) {
  const timelineByMessageId = new Map();
  for (const entry of entries) {
    const eventType = entry[eventTypeKey];
    if (eventType !== 'assistant_message' && eventType !== 'text_end') continue;
    const messageId = entry.message_id;
    const payload = entry[payloadKey];
    const existing = timelineByMessageId.get(messageId);
    const text = typeof payload.content === 'string' ? payload.content : (existing?.text ?? '');
    const completed = eventType === 'text_end' || payload.is_partial === false;
    timelineByMessageId.set(messageId, {
      key: messageId,
      message_id: messageId,
      role: 'assistant',
      text,
      state: completed ? 'completed' : 'streaming',
    });
  }
  const timeline = [...timelineByMessageId.values()];
  return {
    active_message_id:
      timeline.findLast((message) => message.state === 'streaming')?.message_id ?? null,
    timeline,
  };
}

function normalizeWebCapabilitySnapshot(snapshot) {
  const features = Object.fromEntries(
    CAPABILITY_NAMES.map((name) => {
      const capability = snapshot.capabilities[name];
      if (typeof capability.status === 'string') {
        return [
          name,
          {
            status: capability.status,
            available:
              capability.status === 'available' || capability.status === 'degraded',
            reason_code: capability.reason_code,
            service_version: capability.service_version,
            contract_version: capability.contract_version,
            minimum_contract_version: capability.minimum_contract_version,
          },
        ];
      }
      return [
        name,
        {
          available: capability.available,
          reason_code: capability.reason_code,
        },
      ];
    }),
  );
  return { mode: snapshot.mode, features };
}

function normalizeWebHitlAuthority(request) {
  const terminalAt = request.status === 'answered' ? request.answered_at : request.expired_at;
  return {
    request_id: request.request_id,
    request_type: request.request_type,
    status: request.status,
    authority_revision: request.authority_revision,
    terminal_at: terminalAt,
    editable: request.status === 'pending',
  };
}

function normalizeWebWorkspaceSurface(surface) {
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

function normalizeWebArtifactContent(artifact) {
  return {
    artifact_id: artifact.artifact_id,
    mime_type: artifact.mime_type,
    revision: artifact.revision,
    content_hash: artifact.content_hash,
    editable: artifact.editable,
    conflict_safe: artifact.revision === artifact.expected_revision,
    has_idempotency_key: Boolean(artifact.idempotency_key),
  };
}

function normalizeWebSandboxRuntime(runtime) {
  const features = Object.fromEntries(
    ['terminal_interactive', 'terminal_resume', 'files', 'kasm_vnc'].map((name) => {
      const capability = runtime[name];
      return [
        name,
        {
          availability: capability.availability,
          available: ['available', 'degraded'].includes(capability.availability),
          contract_version: capability.contract_version,
          reason_code: capability.reason_code,
        },
      ];
    }),
  );
  return {
    service_version: runtime.service_version,
    contract_version: runtime.contract_version,
    features,
  };
}

function normalizeWebAutomationReceipt(receipt) {
  return {
    contract_version: receipt.contract_version,
    receipt_id: receipt.receipt_id,
    run_id: receipt.run_id,
    job_id: receipt.job_id,
    status: receipt.status,
    duplicate: receipt.duplicate,
    expected_revision: receipt.expected_revision,
    replay_safe: receipt.contract_version === 2 && Boolean(receipt.idempotency_key),
  };
}

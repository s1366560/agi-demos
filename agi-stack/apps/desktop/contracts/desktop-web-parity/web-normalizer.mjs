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

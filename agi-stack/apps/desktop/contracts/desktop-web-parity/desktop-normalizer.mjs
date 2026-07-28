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
  return {
    available: capability.available,
    reason_code: capability.reason_code,
  };
}

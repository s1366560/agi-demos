import type { DevicePageCall } from '../../../agi-stack/packages/plugin-slots/src/richPage';

export function agentChatRuntime(log: HTMLElement, deviceError: string | undefined) {
  const items = [
    { id: 'local', title: 'Local conversation', execution_target: 'local' },
    { id: 'cloud', title: 'Cloud conversation', execution_target: 'cloud' },
  ];
  let completed = '';
  let finish: ((value: unknown) => void) | undefined;
  const calls: unknown[] = [];
  const record = (value: unknown) => {
    calls.push(value);
    log.textContent = JSON.stringify(calls);
  };
  const device: DevicePageCall = ({ tool, payload, digest }) => {
    record({ tool, payload, digest });
    if (deviceError) throw new Error(deviceError);
    if (payload.action === 'stop') {
      completed = 'Device turn cancelled';
      finish?.({ sync: 'synced', status: 'cancelled', executed: true });
      return Promise.resolve({ status: 'cancel_requested' });
    }
    return new Promise((resolve) => {
      finish = resolve;
    });
  };
  function command(name: string, input: Record<string, unknown>) {
    if (name === 'chat-list') return { items };
    if (name === 'chat-create') {
      record({ name, input });
      const row = {
        id: 'new',
        title: 'New test conversation',
        execution_target: String(input.execution_target ?? 'cloud'),
      };
      items.push(row);
      return row;
    }
    if (name === 'chat-history') {
      return { messages: [{ content: completed || 'Saved ' + String(input.conversation_id) }] };
    }
    throw new Error('Unexpected chat fixture command');
  }
  return { device, command, record };
}

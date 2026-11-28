type Packet = { data?: string; message?: string; channel?: string };
export type RunTerminal = { run_id: string; expected_run_revision: number };
type Command = 'project-terminal' | 'project-desktop';
export class SandboxChannel extends EventTarget {
  readonly protocol: string;
  binaryType = 'arraybuffer';
  readyState: number = WebSocket.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  private channel: string | undefined;
  private abort = new AbortController();
  private writes = Promise.resolve();
  private backlog = 0;
  private pendingInput: { text: string; size: number } | undefined;

  constructor(
    private command: Command,
    resolution = '1280x720',
    run?: RunTerminal
  ) {
    super();
    this.protocol = command === 'project-desktop' ? 'binary' : '';
    void this.connect(resolution, run).catch(() => this.fail());
  }

  private async connect(resolution: string, run?: RunTerminal) {
    const { channel } = (await (run
      ? window.memstack.invoke('authorize-run-terminal', { ...run, open_channel: true })
      : window.memstack.invoke(this.command, { action: 'open', resolution }))) as Packet;
    if (!channel) throw new Error('sandbox_channel_unavailable');
    this.channel = channel;
    if (this.abort.signal.aborted) {
      await this.release();
      return;
    }
    this.readyState = WebSocket.OPEN;
    const event = new Event('open');
    this.dispatchEvent(event);
    this.onopen?.(event);
    while (!this.abort.signal.aborted) {
      const packet = (await window.memstack.invoke(
        this.command,
        { action: 'read', channel },
        { signal: this.abort.signal }
      )) as Packet;
      if (this.abort.signal.aborted || (!packet.data && !packet.message)) continue;
      const data =
        packet.message ?? Uint8Array.from(atob(packet.data!), (c) => c.charCodeAt(0)).buffer;
      const message = new MessageEvent('message', { data });
      this.onmessage?.(message);
      this.dispatchEvent(message);
    }
  }

  send(data: string | ArrayBuffer | ArrayBufferView) {
    if (this.readyState !== WebSocket.OPEN) throw new Error('sandbox_channel_closed');
    const bytes =
      typeof data === 'string'
        ? null
        : ArrayBuffer.isView(data)
          ? new Uint8Array(data.buffer, data.byteOffset, data.byteLength).slice()
          : new Uint8Array(data).slice();
    const size = bytes?.length ?? (data as string).length;
    if (this.backlog + size > 256 * 1024) {
      this.fail();
      return;
    }
    this.backlog += size;
    const terminal =
      this.command === 'project-terminal' && typeof data === 'string' ? JSON.parse(data) : null;
    const input =
      terminal?.type === 'input' && typeof terminal.data === 'string' ? terminal.data : null;
    if (
      input !== null &&
      this.pendingInput &&
      this.pendingInput.text.length + input.length <= 4000
    ) {
      this.pendingInput.text += input;
      this.pendingInput.size += size;
      return;
    }
    const batch = input !== null ? { text: input, size } : undefined;
    this.pendingInput = batch;
    this.writes = this.writes
      .then(async () => {
        if (this.pendingInput === batch) this.pendingInput = undefined;
        const write = (text: string) =>
          window.memstack.invoke(
            this.command,
            {
              action: 'write',
              channel: this.channel,
              data: text,
            },
            { signal: this.abort.signal }
          );
        if (bytes) {
          for (let i = 0; i < bytes.length; i += 24 * 1024) {
            await write(btoa(String.fromCharCode(...bytes.subarray(i, i + 24 * 1024))));
          }
        } else {
          await write(
            batch ? JSON.stringify({ type: 'input', data: batch.text }) : (data as string)
          );
        }
      })
      .catch(() => this.fail())
      .finally(() => {
        this.backlog -= batch?.size ?? size;
      });
  }

  private async release() {
    const channel = this.channel;
    this.channel = undefined;
    if (channel)
      await window.memstack.invoke(this.command, { action: 'close', channel }).catch(() => {});
  }

  private fail() {
    if (this.abort.signal.aborted) return;
    const event = new Event('error');
    this.onerror?.(event);
    this.dispatchEvent(event);
    this.close();
  }

  close() {
    if (this.abort.signal.aborted) return;
    this.abort.abort();
    this.readyState = WebSocket.CLOSED;
    void this.release();
    const event = new CloseEvent('close', { code: 1000, wasClean: true });
    this.onclose?.(event);
    this.dispatchEvent(event);
  }
}

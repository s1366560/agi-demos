// Minimal OpenAI-compatible mock LLM server for the desktop runtime audit.
// Speaks POST /v1/chat/completions (JSON and SSE streaming). Responses are
// driven by a programmable handler so each capability audit can script the
// exact assistant behavior it needs (finish JSON, call_tool JSON, or plain
// streamed text). No network access leaves the loopback interface.
import http from 'node:http';

export class MockLlmServer {
  /**
   * @param {(req: {model: string, messages: Array, stream: boolean}, callIndex: number) =>
   *   {kind: 'text', text: string} | {kind: 'json', payload: object}} handler
   */
  constructor(handler) {
    this.handler = handler;
    this.requests = [];
    this.server = null;
    this.port = 0;
  }

  get baseUrl() {
    return `http://127.0.0.1:${this.port}/v1`;
  }

  async start() {
    this.server = http.createServer((req, res) => {
      if (req.method !== 'POST' || !req.url?.endsWith('/chat/completions')) {
        res.writeHead(404, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ error: 'not found' }));
        return;
      }
      let raw = '';
      req.on('data', (chunk) => {
        raw += chunk;
      });
      req.on('end', () => {
        let body;
        try {
          body = JSON.parse(raw);
        } catch {
          res.writeHead(400).end('bad json');
          return;
        }
        this.requests.push({ model: body.model, stream: body.stream === true, messages: body.messages });
        const callIndex = this.requests.length - 1;
        let outcome;
        try {
          outcome = this.handler(body, callIndex);
        } catch (error) {
          res.writeHead(500, { 'content-type': 'application/json' });
          res.end(JSON.stringify({ error: String(error) }));
          return;
        }
        const text =
          outcome.kind === 'json' ? JSON.stringify(outcome.payload) : outcome.text;
        if (body.stream === true) {
          res.writeHead(200, {
            'content-type': 'text/event-stream',
            'cache-control': 'no-cache',
            connection: 'keep-alive',
          });
          const chunkOf = (content) =>
            `data: ${JSON.stringify({
              id: 'chatcmpl-mock',
              object: 'chat.completion.chunk',
              created: 0,
              model: body.model,
              choices: [{ index: 0, delta: { content }, finish_reason: null }],
            })}\n\n`;
          // Emit the text in a few deltas to exercise the streaming path.
          const pieces = text.match(/.{1,24}/gs) ?? [''];
          for (const piece of pieces) res.write(chunkOf(piece));
          res.write(
            `data: ${JSON.stringify({
              id: 'chatcmpl-mock',
              object: 'chat.completion.chunk',
              created: 0,
              model: body.model,
              choices: [{ index: 0, delta: {}, finish_reason: 'stop' }],
            })}\n\n`,
          );
          res.write('data: [DONE]\n\n');
          res.end();
          return;
        }
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(
          JSON.stringify({
            id: 'chatcmpl-mock',
            object: 'chat.completion',
            created: 0,
            model: body.model,
            choices: [
              {
                index: 0,
                message: { role: 'assistant', content: text },
                finish_reason: 'stop',
              },
            ],
            usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
          }),
        );
      });
    });
    await new Promise((resolvePromise) => {
      this.server.listen(0, '127.0.0.1', resolvePromise);
    });
    this.port = this.server.address().port;
    return this;
  }

  async stop() {
    if (!this.server) return;
    await new Promise((resolvePromise) => this.server.close(resolvePromise));
    this.server = null;
  }
}

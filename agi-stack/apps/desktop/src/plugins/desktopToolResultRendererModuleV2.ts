export interface DesktopToolResultRendererModuleV2 {
  readonly moduleRef: 'builtin:structured-tool-result';
  readonly srcDoc: string;
}

export const DESKTOP_TOOL_RESULT_RENDERER_MODULE_REF_V2 = 'builtin:structured-tool-result' as const;

const DESKTOP_TOOL_RESULT_RENDERER_SRC_DOC_V2 = `<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta
      http-equiv="Content-Security-Policy"
      content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; img-src 'none'; font-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"
    >
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
      :root { color-scheme: light dark; font: 11px system-ui, sans-serif; }
      body { margin: 0; background: transparent; color: CanvasText; }
      #surface {
        align-items: center;
        border: 1px solid color-mix(in srgb, CanvasText 16%, transparent);
        border-radius: 6px;
        display: flex;
        gap: 8px;
        min-height: 30px;
        padding: 4px 8px;
      }
      #surface[hidden] { display: none; }
      #result { font-weight: 650; }
      #kind, #tool { opacity: 0.72; }
      #status { margin-left: auto; opacity: 0.72; }
    </style>
  </head>
  <body>
    <section id="surface" hidden>
      <span id="result"></span>
      <span id="kind"></span>
      <code id="tool"></code>
      <span id="status"></span>
    </section>
    <script>
      (() => {
        const SOURCE = 'memstack-plugin-slot';
        const SLOT_ID = 'structured-tool-result';
        const surface = document.getElementById('surface');
        const result = document.getElementById('result');
        const kind = document.getElementById('kind');
        const tool = document.getElementById('tool');
        const status = document.getElementById('status');
        const kinds = new Set(['search', 'read', 'command', 'edit', 'check', 'tool']);
        const statuses = new Set(['complete', 'failed']);
        let disposed = false;

        const send = (message) => {
          if (!disposed) parent.postMessage({ source: SOURCE, message }, '*');
        };
        const resize = () => {
          send({ type: 'slot:resize', slotId: SLOT_ID, height: document.body.scrollHeight });
        };
        const fail = () => {
          send({ type: 'slot:error', slotId: SLOT_ID, message: 'invalid_payload' });
        };
        const render = (payload) => {
          if (
            !payload ||
            payload.schemaVersion !== 1 ||
            typeof payload.resultId !== 'string' ||
            typeof payload.toolName !== 'string' ||
            !kinds.has(payload.kind) ||
            !statuses.has(payload.status) ||
            typeof payload.resultLabel !== 'string' ||
            typeof payload.kindLabel !== 'string' ||
            typeof payload.statusLabel !== 'string'
          ) {
            fail();
            return;
          }
          surface.hidden = false;
          surface.dataset.resultId = payload.resultId;
          surface.dataset.kind = payload.kind;
          surface.dataset.status = payload.status;
          result.textContent = payload.resultLabel;
          kind.textContent = payload.kindLabel;
          tool.textContent = payload.toolName;
          tool.hidden = payload.toolName.length === 0;
          status.textContent = payload.statusLabel;
          resize();
        };
        const receive = (event) => {
          if (disposed || event.source !== parent) return;
          const envelope = event.data;
          if (!envelope || envelope.source !== SOURCE || !envelope.message) return;
          const message = envelope.message;
          if (message.slotId !== SLOT_ID) return;
          if (message.type === 'slot:init') render(message.payload);
          if (message.type === 'slot:event' && message.name === 'tool-result') {
            render(message.data);
          }
          if (message.type === 'slot:dispose') {
            disposed = true;
            window.removeEventListener('message', receive);
            surface.remove();
          }
        };
        window.addEventListener('message', receive);
        send({ type: 'slot:ready', slotId: SLOT_ID });
      })();
    </script>
  </body>
</html>`;

export const DESKTOP_TOOL_RESULT_RENDERER_MODULE_V2: DesktopToolResultRendererModuleV2 =
  Object.freeze({
    moduleRef: DESKTOP_TOOL_RESULT_RENDERER_MODULE_REF_V2,
    srcDoc: DESKTOP_TOOL_RESULT_RENDERER_SRC_DOC_V2,
  });

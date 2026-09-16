export interface DesktopConversationRendererModuleV2 {
  readonly moduleRef: 'builtin:desktop-conversation-renderer';
  readonly srcDoc: string;
}

export const DESKTOP_CONVERSATION_RENDERER_MODULE_REF_V2 =
  'builtin:desktop-conversation-renderer' as const;

const DESKTOP_CONVERSATION_RENDERER_SRC_DOC_V2 = `<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta
      http-equiv="Content-Security-Policy"
      content="default-src 'none'; script-src 'sha256-jaO7hFDfdjXzq8vHHc4PezUMZXZHq42ua3bm7MZy7jQ='; style-src 'unsafe-inline'; connect-src 'none'; img-src 'none'; font-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"
    >
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
      :root { color-scheme: light dark; font: 12px system-ui, sans-serif; }
      body { margin: 0; background: transparent; color: CanvasText; }
      #surface {
        align-items: center;
        display: flex;
        gap: 10px;
        justify-content: space-between;
        min-height: 36px;
        padding: 6px 10px;
      }
      #surface[hidden] { display: none; }
      #state { display: flex; gap: 8px; min-width: 0; opacity: 0.72; }
      #workflow { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      button {
        background: ButtonFace;
        border: 1px solid ButtonBorder;
        border-radius: 6px;
        color: ButtonText;
        cursor: pointer;
        font: inherit;
        padding: 4px 8px;
      }
      button:disabled { cursor: not-allowed; opacity: 0.55; }
    </style>
  </head>
  <body>
    <section id="surface" hidden>
      <div id="state">
        <span id="message-count"></span>
        <span id="workflow"></span>
      </div>
      <button id="commands" type="button"></button>
    </section>
    <script>
      (() => {
        const SOURCE = 'memstack-plugin-slot';
        const SLOT_ID = 'conversation-renderer';
        const surface = document.getElementById('surface');
        const messageCount = document.getElementById('message-count');
        const workflow = document.getElementById('workflow');
        const commands = document.getElementById('commands');
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
            typeof payload.conversationId !== 'string' ||
            !Number.isSafeInteger(payload.messageCount) ||
            typeof payload.workflowTarget !== 'string' ||
            typeof payload.sending !== 'boolean' ||
            typeof payload.disabled !== 'boolean' ||
            typeof payload.commandsLabel !== 'string'
          ) {
            fail();
            return;
          }
          surface.hidden = false;
          surface.dataset.conversationId = payload.conversationId;
          surface.dataset.sending = String(payload.sending);
          messageCount.textContent = String(payload.messageCount);
          workflow.textContent = payload.workflowTarget;
          commands.textContent = payload.commandsLabel;
          commands.setAttribute('aria-label', payload.commandsLabel);
          commands.disabled = payload.disabled;
          resize();
        };
        const receive = (event) => {
          if (disposed || event.source !== parent) return;
          const envelope = event.data;
          if (!envelope || envelope.source !== SOURCE || !envelope.message) return;
          const message = envelope.message;
          if (message.slotId !== SLOT_ID) return;
          if (message.type === 'slot:init') render(message.payload);
          if (message.type === 'slot:event' && message.name === 'conversation-state') {
            render(message.data);
          }
          if (message.type === 'slot:dispose') {
            disposed = true;
            window.removeEventListener('message', receive);
            surface.remove();
          }
        };
        commands.addEventListener('click', () => {
          send({ type: 'slot:action', slotId: SLOT_ID, name: 'open-commands' });
        });
        window.addEventListener('message', receive);
        send({ type: 'slot:ready', slotId: SLOT_ID });
      })();
    </script>
  </body>
</html>`;

export const DESKTOP_CONVERSATION_RENDERER_MODULE_V2: DesktopConversationRendererModuleV2 =
  Object.freeze({
    moduleRef: DESKTOP_CONVERSATION_RENDERER_MODULE_REF_V2,
    srcDoc: DESKTOP_CONVERSATION_RENDERER_SRC_DOC_V2,
  });

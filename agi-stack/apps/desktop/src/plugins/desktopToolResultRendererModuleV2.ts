export interface DesktopToolResultRendererModuleV2 {
  readonly moduleRef: "builtin:structured-tool-result";
  readonly srcDoc: string;
}

export const DESKTOP_TOOL_RESULT_RENDERER_MODULE_REF_V2 =
  "builtin:structured-tool-result" as const;

const DESKTOP_TOOL_RESULT_RENDERER_SRC_DOC_V2 = `<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta
      http-equiv="Content-Security-Policy"
      content="default-src 'none'; script-src 'sha256-Ld13Wx9ubp8tdlKauYzcazdh+4nLB1hgou+GLzjHQFc='; style-src 'unsafe-inline'; connect-src 'none'; img-src blob:; media-src blob:; font-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"
    >
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
      :root { color-scheme: light dark; font: 11px system-ui, sans-serif; }
      body { margin: 0; background: transparent; color: CanvasText; }
      #surface {
        align-items: center;
        border: 1px solid color-mix(in srgb, CanvasText 16%, transparent);
        border-radius: 6px;
        display: block;
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
      <div id="presentation"></div>
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
        const presentation = document.getElementById('presentation');
        const kinds = new Set(['search', 'read', 'command', 'edit', 'check', 'computer_use', 'repl_output', 'tool']);
        const statuses = new Set(['complete', 'failed', 'paused', 'stopped']);
        let disposed = false;
        const mediaUrls = [];
        let previewUrl = null;
        let iconUrl = null;
        const revokePreview = () => {
          for (const url of mediaUrls.splice(0)) URL.revokeObjectURL(url);
          if (previewUrl !== null) URL.revokeObjectURL(previewUrl);
          previewUrl = null;
          if (iconUrl !== null) URL.revokeObjectURL(iconUrl);
          iconUrl = null;
        };

        const send = (message) => {
          if (!disposed) parent.postMessage({ source: SOURCE, message }, '*');
        };
        const resize = () => {
          send({ type: 'slot:resize', slotId: SLOT_ID, height: document.body.scrollHeight });
        };
        const fail = () => {
          revokePreview(); presentation.replaceChildren(); surface.hidden = true;
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
          revokePreview();
          presentation.replaceChildren();
          const view = payload.presentation;
          if (view && view.kind === 'repl_output') {
            if (!Array.isArray(view.entries) || view.entries.length > 256) { fail(); return; }
            let textBytes = 0, mediaBytes = 0;
            const valid = view.entries.every(entry => {
              if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return false;
              if (entry.kind === 'unavailable') return entry.reason === 'media_size_limit';
              if (entry.kind === 'text') return typeof entry.text === 'string' && (textBytes += entry.text.length) <= 32768;
              const image = entry.kind === 'image';
              const types = image ? ['image/png', 'image/jpeg', 'image/webp'] : ['audio/wav', 'audio/x-wav', 'audio/mpeg', 'audio/ogg'];
              return (image || entry.kind === 'audio') && ['device', 'conversation_tool_media'].includes(entry.store) &&
                typeof entry.artifactId === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,255}$/.test(entry.artifactId) &&
                types.includes(entry.mimeType) && Number.isSafeInteger(entry.sizeBytes) && entry.sizeBytes > 0 &&
                entry.sizeBytes <= 10 * 1024 * 1024 && (mediaBytes += entry.sizeBytes) <= 32 * 1024 * 1024;
            });
            if (!valid) { fail(); return; }
            for (const entry of view.entries) {
              if (entry.kind === 'unavailable') { const label = document.createElement('span'); label.textContent = payload.mediaUnavailableLabel; presentation.append(label); continue; }
              if (entry.kind === 'text' && typeof entry.text === 'string') {
                const text = document.createElement('pre'); text.textContent = entry.text;
                text.style.whiteSpace = 'pre-wrap'; presentation.append(text); continue;
              }
              const image = entry.kind === 'image';
              const types = image ? ['image/png', 'image/jpeg', 'image/webp'] : ['audio/wav', 'audio/x-wav', 'audio/mpeg', 'audio/ogg'];
              if ((!image && entry.kind !== 'audio') || !types.includes(entry.mimeType) ||
                  !Number.isSafeInteger(entry.sizeBytes) || entry.sizeBytes < 1 ||
                  entry.sizeBytes > 10 * 1024 * 1024) { fail(); return; }
              const content = Array.isArray(payload.media) && payload.media.find(value => value &&
                value.store === entry.store && value.artifactId === entry.artifactId && value.mimeType === entry.mimeType &&
                value.bytes instanceof Uint8Array && value.bytes.byteLength === entry.sizeBytes);
              if (!content) {
                const pending = document.createElement('span'); pending.textContent = payload.media === undefined ? payload.mediaLoadingLabel : payload.mediaUnavailableLabel;
                presentation.append(pending); continue;
              }
              const url = URL.createObjectURL(new Blob([content.bytes], {type: content.mimeType}));
              mediaUrls.push(url);
              const node = document.createElement(image ? 'img' : 'audio'); node.src = url;
              if (image) { node.alt = payload.resultLabel; node.style.maxWidth = '100%'; node.style.maxHeight = '340px'; node.style.objectFit = 'contain'; node.onload = resize; }
              else { node.controls = true; node.preload = 'metadata'; node.onloadedmetadata = resize; }
              presentation.append(node);
            }
          } else if (view && view.kind === 'computer_use') {
            if (typeof view.app !== 'string' || typeof view.text !== 'string' || typeof view.summary !== 'string') { fail(); return; }
            const icon = payload.computerUseAppIcon;
            if (icon && icon.artifactId === view.appIconArtifactId &&
                ['image/png', 'image/jpeg', 'image/webp'].includes(icon.mimeType) &&
                icon.bytes instanceof Uint8Array && icon.bytes.byteLength > 0 && icon.bytes.byteLength <= 8 * 1024 * 1024) {
              iconUrl = URL.createObjectURL(new Blob([icon.bytes], {type: icon.mimeType}));
              const badge = document.createElement('img'); badge.src = iconUrl; badge.alt = '';
              badge.style.width = '24px'; badge.style.height = '24px'; badge.style.objectFit = 'contain'; badge.style.verticalAlign = 'middle'; badge.style.marginRight = '6px'; presentation.append(badge);
            }
            const title = document.createElement('strong'); title.textContent = view.app; presentation.append(title);
            const identity = [view.windowTitle, view.windowId, view.observedAt].filter(value => typeof value === 'string' && value.length > 0);
            if (identity.length) { const meta = document.createElement('p'); meta.textContent = identity.join(' · '); meta.style.opacity = '0.7'; presentation.append(meta); }
            const summary = document.createElement('p'); summary.textContent = view.summary; presentation.append(summary);
            const preview = payload.computerUsePreview;
            if (preview && preview.artifactId === view.screenshotArtifactId &&
                ['image/png', 'image/jpeg', 'image/webp'].includes(preview.mimeType) &&
                preview.bytes instanceof Uint8Array && preview.bytes.byteLength > 0 && preview.bytes.byteLength <= 8 * 1024 * 1024) {
              previewUrl = URL.createObjectURL(new Blob([preview.bytes], {type: preview.mimeType}));
              const img = document.createElement('img'); img.src = previewUrl; img.alt = view.app;
              img.className = 'computer-use-observation-preview';
              img.style.maxWidth = '100%'; img.style.maxHeight = '340px'; img.style.objectFit = 'contain'; img.onload = resize;
              if (iconUrl) { const frame = document.createElement('div'); frame.style.position = 'relative'; frame.append(img); const badge = document.createElement('img'); badge.src = iconUrl; badge.alt = ''; badge.style.position = 'absolute'; badge.style.right = '8px'; badge.style.bottom = '8px'; badge.style.width = '32px'; badge.style.height = '32px'; badge.style.objectFit = 'contain'; frame.append(badge); presentation.append(frame); }
              else { presentation.append(img); }
            }
            const pre = document.createElement('pre'); pre.style.whiteSpace = 'pre-wrap'; pre.style.maxHeight = '220px'; pre.style.overflow = 'auto';
            pre.textContent = view.text; presentation.append(pre);
          } else if (view && (view.kind === 'text' || view.kind === 'summary')) {
            const pre = document.createElement('pre'); pre.style.whiteSpace = 'pre-wrap';
            pre.textContent = view.kind === 'text' ? view.text : view.summary; presentation.append(pre);
          } else if (view && view.kind === 'diff') {
            for (const [label, body] of [['Before', view.before], ['After', view.after]]) {
              const pre = document.createElement('pre'); pre.textContent = label + String.fromCharCode(10) + body; presentation.append(pre);
            }
          } else if (view && view.kind === 'table') {
            const table = document.createElement('table');
            for (const [index, row] of [view.columns, ...view.rows].entries()) {
              const tr = document.createElement('tr');
              for (const cell of row) { const td = document.createElement(index === 0 ? 'th' : 'td'); td.textContent = cell; tr.append(td); }
              table.append(tr);
            }
            presentation.append(table);
          }
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
            revokePreview();
            disposed = true;
            window.removeEventListener('message', receive);
            surface.remove();
          }
        };
        window.addEventListener('message', receive);
        window.addEventListener('unload', revokePreview, {once: true});
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

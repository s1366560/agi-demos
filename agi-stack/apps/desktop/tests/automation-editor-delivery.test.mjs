import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const dialogSource = readFileSync(
  resolve(here, '../src/features/automations/AutomationEditorDialog.tsx'),
  'utf8',
);

// The backend stores cron delivery kinds but never executes webhook/announce
// fan-out, and the dialog never collects the webhook URL the schema requires.
// Offering those options lets users save a job that silently delivers nothing,
// so the editor must not surface them (matching the web app, which exposes no
// delivery picker at all).
test('automation editor does not offer undeliverable webhook or announce options', () => {
  assert.ok(
    !dialogSource.includes("t('automations.form.deliveryWebhook')"),
    'webhook delivery option must not be rendered',
  );
  assert.ok(
    !dialogSource.includes("t('automations.form.deliveryAnnounce')"),
    'announce delivery option must not be rendered',
  );
  assert.ok(
    !dialogSource.includes("t('automations.form.delivery')"),
    'the delivery picker itself must not be rendered',
  );
});

test('automation editor preserves a stored delivery kind when editing', () => {
  assert.match(dialogSource, /delivery:\s*\{ kind: draft\.deliveryKind, config: \{\} \}/u);
  assert.match(dialogSource, /isDeliveryKind\(job\?\.delivery\.kind\) \? job\.delivery\.kind : 'none'/u);
});

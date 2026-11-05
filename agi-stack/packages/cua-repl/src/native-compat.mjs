import { duration, imageBytes, index, point, selectionCursor, target } from './values.mjs';

const fields = Object.freeze({
  click: ['element_index', 'x', 'y', 'mouse_button', 'click_count', 'key', 'duration'],
  drag: ['from_x', 'from_y', 'to_x', 'to_y'],
  paste: ['text', 'format'],
  perform_secondary_action: ['element_index', 'action'],
  press_key: ['key', 'duration'],
  scroll: ['element_index', 'x', 'y', 'direction', 'pages'],
  select_text: ['element_index', 'text', 'prefix', 'suffix', 'selection_type'],
  set_value: ['element_index', 'value'],
  type_text: ['text'],
});

function input(value, allowed) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new TypeError('native input must be an object');
  for (const name of Object.keys(value)) if (!allowed.includes(name)) throw new TypeError(`unknown native input field ${name}`);
  if (typeof value.app !== 'string' || !value.app) throw new TypeError('native input requires an app identifier');
  return value;
}

const text = (value, name) => {
  if (typeof value !== 'string') throw new TypeError(`${name} must be a string`);
  return value;
};

function held(value, platform) {
  if (value === undefined) return {};
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 30) throw new TypeError('duration must be between 0 and 30 seconds');
  return duration(value * 1000, platform);
}

function translate(name, args, platform) {
  const value = { ...args };
  delete value.app;
  if (name === 'click' || name === 'scroll') {
    if (value.element_index !== undefined && (value.x !== undefined || value.y !== undefined)) throw new TypeError('choose an element index or a point');
    const selected = target(value.element_index ?? { x: value.x, y: value.y });
    Object.assign(value, selected);
    if (name === 'click') {
      value.mouse_button ??= 'left'; value.click_count ??= 1;
      if (!['left', 'right', 'middle', 'l', 'r', 'm'].includes(value.mouse_button)) throw new TypeError('invalid mouse button');
      if (!Number.isSafeInteger(value.click_count) || value.click_count < 1) throw new TypeError('click_count must be a positive integer');
    } else {
      if (!['up', 'down', 'left', 'right', 'u', 'd', 'l', 'r'].includes(value.direction)) throw new TypeError('invalid scroll direction');
      if (value.pages !== undefined && (!Number.isFinite(value.pages) || value.pages <= 0)) throw new TypeError('pages must be positive');
    }
  }
  if (name === 'drag') {
    point({ x: value.from_x, y: value.from_y }); point({ x: value.to_x, y: value.to_y });
  }
  if (['perform_secondary_action', 'select_text', 'set_value'].includes(name)) index(value.element_index);
  if (['paste', 'select_text', 'type_text'].includes(name)) text(value.text, 'text');
  if (name === 'set_value') text(value.value, 'value');
  if (name === 'perform_secondary_action') text(value.action, 'action');
  if (name === 'press_key') text(value.key, 'key');
  if (name === 'paste') {
    value.format ??= 'text';
    if (!['text', 'md', 'html'].includes(value.format)) throw new TypeError('unsupported paste format');
  }
  if (name === 'select_text') {
    if (value.prefix !== undefined) text(value.prefix, 'prefix');
    if (value.suffix !== undefined) text(value.suffix, 'suffix');
    if (value.selection_type !== undefined && !['text', 'cursor_before', 'cursor_after'].includes(value.selection_type)) throw new TypeError('invalid selection_type');
    value.cursor = selectionCursor(value.selection_type); delete value.selection_type;
  }
  if (name === 'click' || name === 'press_key') {
    Object.assign(value, held(value.duration, platform)); delete value.duration;
  }
  return value;
}

export function rawNative({ call, listApps, observe, latest, platform }) {
  const api = {
    target: platform === 'darwin' ? 'mac' : platform === 'win32' ? 'windows' : 'linux',
    list_apps: () => listApps({ emit: false }),
    launch_app: async args => {
      input(args, ['app']);
      await call('computer_launch_app', { app: args.app });
    },
    get_app_state: async args => {
      input(args, ['app', 'disableDiff']);
      if (args.disableDiff !== undefined && typeof args.disableDiff !== 'boolean') throw new TypeError('disableDiff must be a boolean');
      const result = await observe(args.app, { disable_diff: args.disableDiff ?? false });
      const bytes = result.screenshot ? imageBytes(result.screenshot) : undefined;
      const mimeType = result.screenshot?.mimeType ?? result.screenshot?.mime_type ?? 'image/png';
      const url = typeof result.screenshot?.url === 'string' && result.screenshot.url.startsWith('data:image/')
        ? result.screenshot.url : bytes ? `data:${mimeType};base64,${Buffer.from(bytes).toString('base64')}` : undefined;
      return { app: result.app ?? args.app, text: result.text ?? result.state ?? '', screenshot: url ? { url } : null };
    },
  };
  for (const name of Object.keys(fields)) api[name] = async args => {
    input(args, ['app', ...fields[name]]);
    const value = translate(name, args, platform);
    const observation = latest.get(args.app);
    if (!observation?.snapshot_id) throw new Error('observe the app before input; no current snapshot identity');
    const tool = name === 'perform_secondary_action' ? 'computer_secondary_action' : `computer_${name}`;
    await call(tool, { app: args.app, snapshot_id: observation.snapshot_id,
      ...(observation.window_id ? { window_id: observation.window_id } : {}), ...value });
  };
  return api;
}

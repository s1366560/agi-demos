import { duration, imageBytes, index, point, selectionCursor, stringValue, target, unwrap } from './values.mjs';
import { rawNative } from './native-compat.mjs';
import { nativeAudio } from './audio.mjs';

export function nativeSurface({ rpc, write, emitImage, platform, temporaryDirectory }) {
  const call = async (tool, args = {}) => unwrap(await rpc('computer.call', { tool, arguments: args }));
  const latest = new Map();
  const observeApp = async (app, args) => {
    const previous = latest.get(app);
    for (const [key, value] of latest) if (key === app || value === previous) latest.delete(key);
    const observation = await call('computer_get_app_state', { app, ...args });
    latest.set(app, observation);
    if (typeof observation.app === 'string') latest.set(observation.app, observation);
    return observation;
  };
  const stopAudio = (options = {}) => {
    if (!options || typeof options !== 'object' || Array.isArray(options)) throw new TypeError('audio.stop options must be an object');
    const { save, ...args } = options;
    if (save !== undefined && save !== true) throw new TypeError('audio.stop always saves the recording; save:false is not supported');
    return call('computer_audio_stop', args);
  };
  const listApps = async ({ emit = true } = {}) => {
    const result = await call('computer_list_apps');
    const apps = (result.apps ?? result).map(app => ({ ...app, displayName: app.displayName ?? app.display_name, isRunning: app.isRunning ?? app.is_running }));
    if (emit) write(apps);
    return apps;
  };
  const listWindows = async ({ emit = true } = {}) => {
    const apps = await listApps({ emit: false });
    const windows = (await Promise.all(apps.filter(app => app.isRunning).map(async app => {
      const result = await call('computer_list_windows', { app: app.id });
      return (result.windows ?? []).map(window => ({ ...window, app: app.id }));
    }))).flat();
    if (emit) write(windows);
    return windows;
  };
  const getApp = async (reference) => {
    let app;
    let windowId;
    if (typeof reference === 'string' && reference) app = reference;
    else if (Number.isSafeInteger(reference?.windowId)) {
      const matches = (await listWindows({ emit: false })).filter(w => String(w.id ?? w.window_id) === String(reference.windowId));
      if (matches.length !== 1) throw new Error('window reference is missing or ambiguous');
      app = matches[0].app;
      windowId = String(reference.windowId);
    } else throw new TypeError('getApp requires an app identifier or windowId');
    if (platform === 'darwin') {
      const resolved = await call('computer_resolve_app', { app });
      if (typeof resolved?.app !== 'string' || !resolved.app || typeof resolved.identity_digest !== 'string' || !resolved.identity_digest) throw new Error('host did not resolve a verified application identity');
      const running = resolved.status === 'running' || (Number.isSafeInteger(resolved.process_id) && resolved.process_id > 0);
      if (resolved.status === 'not_running') {
        if (windowId) throw new Error('selected window target is no longer running');
        await call('computer_launch_app', { app: resolved.app });
      } else if (!running) throw new Error('host did not resolve the application target state');
    }
    let observation;
    const observe = async (options = {}, includeImage = false) => {
      observation = undefined;
      observation = await observeApp(app, { ...(windowId ? { window_id: windowId } : {}), disable_diff: options.disableDiffing ?? false });
      const state = observation.text ?? observation.state ?? '';
      const screenshot = includeImage ? imageBytes(observation.screenshot) : undefined;
      if (options.emit !== false) {
        write(state);
        if (screenshot) emitImage({ bytes: screenshot, mimeType: observation.screenshot.mimeType ?? observation.screenshot.mime_type });
      }
      return { state, ...(screenshot ? { screenshot } : {}) };
    };
    const action = async (tool, args) => {
      if (!observation?.snapshot_id) throw new Error('observe the app before input; no current snapshot identity');
      return call(tool, { app, snapshot_id: observation.snapshot_id,
        ...(observation.window_id ?? windowId ? { window_id: observation.window_id ?? windowId } : {}), ...args });
    };
    const handle = {
      getAXState: async options => (await observe(options)).state,
      getScreenshot: async (options = {}) => {
        const { screenshot } = await observe({ ...options, emit: false }, true);
        if (!screenshot) throw new Error('host did not provide authorized screenshot bytes');
        if (options.emit !== false) emitImage({ bytes: screenshot, mimeType: observation.screenshot.mimeType ?? observation.screenshot.mime_type });
        return screenshot;
      },
      getAXStateAndScreenshot: options => observe(options, true),
      click: (value, options = {}) => action('computer_click', { ...target(value), mouse_button: options.mouseButton ?? 'left', click_count: options.clickCount ?? 1,
        ...(options.key ? { key: options.key } : {}), ...duration(options.durationMs, platform) }),
      drag: (from, to) => { from = point(from); to = point(to); return action('computer_drag', { from_x: from.x, from_y: from.y, to_x: to.x, to_y: to.y }); },
      scroll: (value, direction, distance = 1) => action('computer_scroll', { ...target(value), direction, ...(typeof distance === 'number' ? { pages: distance } : { pixels: distance.pixels }) }),
      selectText: (elementIndex, text, options = {}) => action('computer_select_text', { element_index: index(elementIndex), text, ...(options.prefix !== undefined ? { prefix: options.prefix } : {}),
        ...(options.suffix !== undefined ? { suffix: options.suffix } : {}), cursor: selectionCursor(options.selectionType) }),
      setValue: (elementIndex, value) => action('computer_set_value', { element_index: index(elementIndex), value: stringValue(value) }),
      performSecondaryAction: (elementIndex, actionName) => action('computer_secondary_action', { element_index: index(elementIndex), action: actionName }),
      paste: (text, options = {}) => action('computer_paste', { text, format: options.format ?? 'text' }),
      pressKey: (key, options = {}) => action('computer_press_key', { key, ...duration(options.durationMs, platform) }),
      typeText: (text, elementIndex) => action('computer_type_text', { text, ...(elementIndex === undefined ? {} : { element_index: index(elementIndex) }) }),
    };
    if (platform === 'linux') handle.typeCharacters = text => action('computer_type_text', { text, characters: true });
    await observe({ disableDiffing: true });
    return Object.freeze(handle);
  };
  const audio = nativeAudio({ call, temporaryDirectory });
  const computer = Object.freeze({ ...rawNative({ call, listApps, observe: observeApp, latest, platform }),
    start_audio_recording: audio.start_audio_recording, stop_audio_recording: audio.stop_audio_recording,
    listApps, listWindows, getApp,
    capabilities: () => call('computer_capabilities'),
    lockedUse: options => call('computer_locked_use', options),
    audio: Object.freeze({ start: options => call('computer_audio_start', { max_duration_ms: 60_000, ...options }), status: options => call('computer_audio_status', options), stop: stopAudio }),
    clipboard: Object.freeze({ read: options => call('computer_clipboard_read', options), write: options => call('computer_clipboard_write', options), release: options => call('computer_clipboard_release', options) }) });
  return { getApp, listApps, listWindows, computer };
}

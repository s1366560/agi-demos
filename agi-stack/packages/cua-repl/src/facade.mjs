import { nativeSurface } from './native.mjs';
import { browserSurface } from './browser.mjs';
import { browserDocumentation, capabilityDocumentation } from './browser-docs.mjs';

const CORE_DOC = [
  'CUA: start with getState() or initialize() for fresh inventory, getApp(app), getBrowser({id}), getTab(id,{browser}), or createBrowserTab(browser,url). macOS getApp resolves an installed app identity and requests authorized background launch when it is not running. getBrowser only selects; getTab only binds existing tabs. Read fresh state before choosing element indices. Objects belong to this session and become invalid after reset or authority revocation.',
  'Bound apps and tabs provide getAXState(), getScreenshot(), getAXStateAndScreenshot(), click(index|[x,y]), drag([x,y],[x,y]), scroll(), selectText(), setValue(elementIndex, value), and performSecondaryAction(). For setValue, elementIndex is the numeric index from that target\'s fresh AX snapshot and value must be a string; an empty string clears the value. Input uses the latest observed snapshot and window. Raw macOS cua.computer has target:"mac", list_apps(), get_app_state({app,disableDiff?}), click(), drag(), paste(), perform_secondary_action(), press_key(), scroll(), select_text(), set_value({app,element_index,value}), and type_text(). Raw actions take {app,...}; observe that app first. Raw held duration is in seconds; bound durationMs is in milliseconds. Selection types are text, cursor_before, cursor_after.',
  'System audio compatibility: await cua.computer.start_audio_recording({max_duration_ms:5000}); later const audio=await cua.computer.stop_audio_recording(); await nodeRepl.emitAudio(audio). Durations are integers from 100 through 300000ms, default 60000ms. stop returns {filepath,bytes,data_url} for a 24kHz stereo WAV in the private temporary directory. Emit the original audio object to attach large recordings; arbitrary large bytes or data URLs cannot use the inline output channel. Final result previews are bounded; variables retain their full values.',
  'Extended audio: const recording=await cua.computer.audio.start({source:"microphone"}); sources are microphone, system, or mixed. audio.status({recording_id}) and audio.stop({recording_id}) select an owned recording; omitting options selects recordings in this session. Stop always saves; the legacy save:true alias is accepted and save:false is rejected. Inline receipt.media may be passed to nodeRepl.emitAudio; larger saved recordings remain available in the desktop recording UI.',
  'nodeRepl.write(value,itemId?) emits text with an optional stable item identity. nodeRepl.requestMeta is read-only host turn context. rewriteDocumentation() replays documentation into the current context. Locked use: await cua.computer.lockedUse({enabled:true}); the host owns renewal and releases when the active cell finishes, pauses, or stops. Disable with {enabled:false}.',
].join('\n');

export function createFacade(options) {
  const { write, enabledSurfaces = ['computer', 'browser'], getRequestMeta = () => undefined } = options;
  if (!Array.isArray(enabledSurfaces) || !enabledSurfaces.length || enabledSurfaces.some(s => !['computer', 'browser'].includes(s))) throw new TypeError('enabledSurfaces must contain computer and/or browser');
  const emitted = new Map();
  const document = async (name = 'core', force = false) => {
    const text = name === 'core' ? CORE_DOC : name.startsWith('capability:') ? capabilityDocumentation[name.slice('capability:'.length)] : browserDocumentation;
    if (!text) throw new Error(`documentation is unavailable for ${name}`);
    if (!emitted.has(name) || force) {
      const itemId = name === 'core' ? 'cua.core' : name.startsWith('browser:') ? `cua.browser.${name.slice(8)}` : `cua.capability.${name.slice(11)}`;
      write(text, itemId); emitted.set(name, { text, itemId, requestMeta: getRequestMeta() });
    }
    return text;
  };
  const api = {};
  if (enabledSurfaces.includes('computer')) Object.assign(api, nativeSurface(options));
  if (enabledSurfaces.includes('browser')) Object.assign(api, browserSurface({ ...options, document }));
  for (const name of ['getApp', 'getBrowser', 'getTab', 'createBrowserTab']) if (api[name]) {
    const method = api[name];
    api[name] = async (...args) => { await document(); return method(...args); };
  }
  api.getState = async ({ emit = true } = {}) => {
    await document();
    const state = { apps: [], browsers: [] };
    const errors = [];
    if (api.listApps) try { state.apps = await api.listApps({ emit: false }); } catch (error) { errors.push(`computer: ${error.message}`); }
    if (api.listBrowsers) try {
      const browsers = await api.listBrowsers({ emit: false });
      const entries = await Promise.all(browsers.map(async browser => {
        try { return { browser: { ...browser, tabs: await api.listTabs({ browser: browser.id, emit: false }) } }; }
        catch (error) { return { browser: { ...browser, tabs: [] }, error: `browser ${browser.id}: ${error.message ?? String(error)}` }; }
      }));
      state.browsers = entries.map(entry => entry.browser);
      errors.push(...entries.flatMap(entry => entry.error ? [entry.error] : []));
    } catch (error) { errors.push(`browser: ${error.message}`); }
    if (errors.length) state.errors = errors;
    if (emit) write(state, 'cua.state');
    return state;
  };
  api.initialize = api.getState;
  api.rewriteDocumentation = async () => {
    if (!emitted.size) await document();
    else for (const entry of emitted.values()) {
      const requestMeta = getRequestMeta();
      if (requestMeta !== undefined && requestMeta === entry.requestMeta) continue;
      write(entry.text, entry.itemId); entry.requestMeta = requestMeta;
    }
  };
  return Object.freeze(api);
}

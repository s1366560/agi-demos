(async () => {
  const api = window.memstack;
  const scope = await api.scope();
  const zh = scope.locale.startsWith('zh');
  const text = (english, chinese) => zh ? chinese : english;
  const root = document.getElementById('root');
  function element(tag, value) {
    const node = document.createElement(tag);
    if (value !== undefined) node.textContent = value;
    return node;
  }
  const title = element('h1', text('Project sandbox', '项目沙箱'));
  const status = element('output');
  const notice = element('p');
  notice.setAttribute('role', 'alert');
  const profile = element('select');
  for (const name of ['standard', 'lite', 'full']) profile.append(element('option', name));
  const profileLabel = element('label', text('Sandbox profile', '沙箱配置'));
  profileLabel.append(profile);
  const refresh = element('button', text('Refresh', '刷新'));
  const prepare = element('button', text('Prepare sandbox', '准备沙箱'));
  const terminal = element('fieldset');
  terminal.append(element('legend', text('Run terminal authorization', '运行终端授权')));
  function input(label, type) {
    const wrapper = element('label', label);
    const field = element('input');
    field.type = type;
    field.required = true;
    if (type === 'number') { field.min = '1'; field.step = '1'; }
    wrapper.append(field);
    terminal.append(wrapper);
    return field;
  }
  const run = input(text('Run ID', '运行 ID'), 'text');
  const revision = input(text('Current run revision', '当前运行修订号'), 'number');
  const authorize = element('button', text('Request terminal authorization', '申请终端授权'));
  const availability = element('p');
  const result = element('output');
  terminal.append(authorize, result);
  root.append(title, status, refresh, profileLabel, prepare, availability, terminal, notice);
  async function load() {
    terminal.disabled = true;
    result.textContent = '';
    const state = await api.invoke('sandbox-status');
    status.textContent = state.sandbox ? state.sandbox.sandbox_id + ' · ' + state.sandbox.status :
      text('No project sandbox', '项目尚无沙箱');
    availability.textContent = state.terminal.reason_code || state.terminal.availability;
    terminal.disabled = state.terminal.availability !== 'available' || !scope.commands.includes('authorize-run-terminal');
  }
  function action(button, callback) {
    button.onclick = async () => {
      button.disabled = true;
      notice.textContent = '';
      try { await callback(); }
      catch (error) { notice.textContent = String(error); }
      finally { button.disabled = false; }
    };
  }
  action(refresh, load);
  action(prepare, async () => {
    await api.invoke('prepare-sandbox', { profile: profile.value });
    await load();
  });
  prepare.disabled = !scope.commands.includes('prepare-sandbox');
  action(authorize, async () => {
    result.textContent = '';
    if (!run.reportValidity() || !revision.reportValidity()) return;
    const grant = await api.invoke('authorize-run-terminal', { run_id: run.value, expected_run_revision: revision.valueAsNumber });
    result.textContent = text('Authorized through ', '授权有效至 ') + grant.expires_at;
  });
  try { await load(); }
  catch (error) { notice.textContent = String(error); }
})();

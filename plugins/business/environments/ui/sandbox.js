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
  const detail = element('dl');
  const metrics = element('dl');
  const usage = element('button', text('Load resource usage', '读取资源用量'));
  usage.disabled = true;
  let sandboxId = null;
  const formatBytes = bytes => new Intl.NumberFormat(scope.locale, {
    style:'unit', unit:'megabyte', maximumFractionDigits:2,
  }).format(bytes / 1000000);
  function row(list, label, value) {
    if (value != null) list.append(element('dt', label), element('dd', String(value)));
  }
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
  const authorize = element('button', text('Open authorized run terminal', '打开已授权运行终端'));
  const availability = element('p');
  const result = element('output');
  terminal.append(authorize, result);
  root.append(title, status, refresh, detail, usage, metrics, profileLabel, prepare, availability, terminal, notice);
  async function load() {
    terminal.disabled = true;
    usage.disabled = true;
    sandboxId = null;
    detail.replaceChildren();
    metrics.replaceChildren();
    result.textContent = '';
    const state = await api.invoke('sandbox-status');
    status.textContent = state.sandbox ? state.sandbox.sandbox_id + ' · ' + state.sandbox.status :
      text('No project sandbox', '项目尚无沙箱');
    if (state.sandbox) {
      sandboxId = state.sandbox.sandbox_id;
      usage.disabled = false;
      row(detail, text('Health', '健康状态'), state.sandbox.is_healthy ? text('Healthy','健康') : text('Unhealthy','异常'));
      row(detail, text('Created at', '创建时间'), state.sandbox.created_at);
      row(detail, text('Last accessed', '最近访问'), state.sandbox.last_accessed_at);
    }
    availability.textContent = state.terminal.reason_code || state.terminal.availability;
    terminal.disabled = state.terminal.availability !== 'available' || !scope.commands.includes('authorize-run-terminal');
  }
  function action(button, callback) {
    button.onclick = async () => {
      button.disabled = true;
      notice.textContent = '';
      try { await callback(); }
      catch (error) { notice.textContent = String(error); }
      finally { button.disabled = button === usage && !sandboxId; }
    };
  }
  action(usage, async () => {
    const selected = sandboxId;
    if (!selected) return;
    const {metrics: state} = await api.invoke('sandbox-status', {metrics_for:selected});
    if (sandboxId !== selected) return;
    metrics.replaceChildren();
    row(metrics, text('CPU usage', 'CPU 用量'), state.cpu_percent + '%');
    row(metrics, text('Memory used', '已用内存'), formatBytes(state.memory_usage));
    row(metrics, text('Memory limit', '内存上限'), formatBytes(state.memory_limit));
    if (state.disk_usage != null) row(metrics, text('Disk used', '磁盘用量'), formatBytes(state.disk_usage));
    if (state.network_rx_bytes != null) row(metrics, text('Network received','网络接收'), formatBytes(state.network_rx_bytes));
    if (state.network_tx_bytes != null) row(metrics, text('Network sent','网络发送'), formatBytes(state.network_tx_bytes));
    row(metrics, text('Processes', '进程数'), state.pids);
    row(metrics, text('Collected at', '采集时间'), state.collected_at);
  });
  action(refresh, load);
  action(prepare, async () => {
    await api.invoke('prepare-sandbox', { profile: profile.value });
    await load();
  });
  prepare.disabled = !scope.commands.includes('prepare-sandbox');
  action(authorize, async () => {
    result.textContent = '';
    if (!run.reportValidity() || !revision.reportValidity()) return;
    const query = new URLSearchParams({run_id: run.value, revision: String(revision.valueAsNumber)});
    await api.navigate(scope.pathname.replace(/\/runtime$/, '/connect') + '?' + query);
  });
  try { await load(); }
  catch (error) { notice.textContent = String(error); }
})();

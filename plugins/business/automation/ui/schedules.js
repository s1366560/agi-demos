(async () => {
  const api = window.memstack;
  const scope = await api.scope();
  const t = (en, zh) => scope.locale.startsWith('zh') ? zh : en;
  function element(tag, text) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    return node;
  }
  const panel = element('fieldset');
  const status = element('p');
  status.setAttribute('role', 'status');
  const history = element('ol');
  history.setAttribute('aria-live', 'polite');
  const title = element('h1', t('Project schedules', '项目计划任务'));
  function field(title, input) {
    const label = element('label', title);
    label.append(input);
    panel.append(label);
    return input;
  }
  function input(title, attributes) {
    return field(title, Object.assign(element('input'), attributes));
  }
  const job = field(t('Schedule', '计划任务'), element('select'));
  const name = input(t('Name', '名称'), {required: true, maxLength: 255});
  const description = field(t('Description', '说明'), element('textarea'));
  description.maxLength = 1000;
  const kind = field(t('Trigger', '触发方式'), element('select'));
  kind.add(new Option(t('Recurring interval', '固定间隔'), 'every'));
  kind.add(new Option(t('One time', '单次运行'), 'at'));
  kind.add(new Option(t('Cron expression', 'Cron 表达式'), 'cron'));
  const interval = input(t('Interval in seconds', '间隔秒数'), {type:'number', min:'1', max:'31536000', required:true});
  const instant = input(t('Run at (ISO 8601 with offset)', '运行时间（含时区的 ISO 8601 时间）'), {required:true});
  const expression = input(t('Cron expression', 'Cron 表达式'), {required:true, maxLength:256});
  const zone = input(t('Time zone', '时区'), {required:true, maxLength:128});
  const enabled = input(t('Run on schedule', '启用定时运行'), {type:'checkbox'});
  const current = () => rows.find(item => item.id === job.value);
  const operations = new Map();
  let rows = [], offset = 0, total = 0, originalTrigger = null;
  function trigger() {
    if (kind.value === 'at') return {kind:'at', run_at:instant.value};
    if (kind.value === 'cron') return {kind:'cron', expr:expression.value, timezone:zone.value};
    return {kind:'every', interval_seconds:interval.valueAsNumber};
  }
  function showTrigger() {
    for (const [control, type] of [[interval,'every'],[instant,'at'],[expression,'cron'],[zone,'cron']]) {
      control.parentElement.hidden = kind.value !== type;
      control.disabled = kind.value !== type;
    }
  }
  function select() {
    const row = current();
    name.value = row?.name ?? '';
    description.value = row?.description ?? '';
    const schedule = row?.schedule, config = schedule?.config ?? {};
    kind.value = schedule?.kind ?? 'every';
    interval.value = String(config.interval_seconds ?? row?.interval_seconds ?? 60);
    expression.value = config.expr ?? '0 9 * * *';
    zone.value = config.timezone ?? row?.timezone ?? 'UTC';
    instant.value = config.run_at ?? '';
    enabled.checked = row?.enabled ?? false;
    originalTrigger = row ? JSON.stringify(trigger()) : null;
    showTrigger();
    run.disabled = !row || !scope.commands.includes('run-schedule');
    save.disabled = !scope.commands.includes('save-schedule');
    showHistory.disabled = !row;
    history.replaceChildren();
  }
  async function load(id) {
    const page = await api.invoke('list-schedules', {offset});
    rows = page.items; total = page.total;
    job.replaceChildren(new Option(t('New schedule', '新建计划任务'), ''));
    for (const row of rows) job.add(new Option(row.name,row.id));
    job.value = rows.some(row => row.id === id) ? id : '';
    select();
    previous.disabled = offset === 0;
    next.disabled = offset + rows.length >= total;
  }
  function action(label, work) {
    const button = element('button', label);
    button.type = 'button';
    button.onclick = async () => {
      panel.disabled = true;
      try { await work(); } catch (error) { status.textContent = String(error); }
      finally { panel.disabled = false; }
    };
    panel.append(button);
    return button;
  }
  async function mutate(command, payload) {
    const request = JSON.stringify([command,payload]);
    if (!operations.has(request)) operations.set(request, Array.from(crypto.getRandomValues(new Uint32Array(4)), n => n.toString(16).padStart(8,'0')).join(''));
    const receipt = await api.invoke(command, {...payload, idempotency_key:operations.get(request)});
    operations.delete(request);
    return receipt;
  }
  const save = action(t('Save schedule','保存计划任务'), async () => {
    if (![name, description, interval, instant, expression, zone].every(control => control.reportValidity())) return;
    const row = current();
    const payload = {name:name.value, enabled:enabled.checked, description:description.value,
      ...(row && {job_id:row.id, expected_revision:row.revision})};
    if (!row || JSON.stringify(trigger()) !== originalTrigger) payload.trigger = trigger();
    const result = await mutate('save-schedule', payload);
    status.textContent = t('Schedule saved', '计划任务已保存');
    offset = 0;
    await load(result.id);
  });
  const run = action(t('Run now', '立即运行'), async () => {
    const row = current();
    if (!row) return;
    const receipt = await mutate('run-schedule', {job_id:row.id, expected_revision:row.revision});
    status.textContent = receipt.status + ' · ' + receipt.run_id;
  });
  const showHistory = action(t('Run history', '运行记录'), async () => {
    const row = current();
    if (!row) return;
    const result = await api.invoke('list-schedules', {job_id:row.id});
    history.replaceChildren(...result.items.map(item =>
      element('li', [item.started_at,item.status,item.id].join(' · '))));
    status.textContent = result.total ? String(result.total) : t('No runs yet', '暂无运行记录');
  });
  const previous = action(t('Previous page','上一页'), async () => {offset = Math.max(0,offset-32); await load();});
  const next = action(t('Next page','下一页'), async () => {offset += 32; await load();});
  const refresh = action(t('Refresh','刷新'), () => load(job.value));
  kind.onchange = showTrigger;
  job.onchange = select;
  previous.disabled = next.disabled = run.disabled = showHistory.disabled = save.disabled = true;
  document.getElementById('root').append(title, panel, status, history);
  refresh.click();
})();

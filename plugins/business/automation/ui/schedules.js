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
  function selectField(label, choices) {
    const control = field(label, element('select'));
    for (const [value, title] of choices) control.add(new Option(title,value));
    return control;
  }
  const payloadType = selectField(t('Action','任务操作'), [
    ['system_event', t('System event','系统事件')], ['agent_turn',t('Agent message','智能体消息')]
  ]);
  const actionText = field(t('Message','消息内容'),element('textarea'));
  actionText.maxLength = 32768;
  const conversation = selectField(t('Conversation','会话'),[
    ['reuse',t('Reuse conversation','复用会话')], ['fresh',t('New conversation','创建新会话')]
  ]);
  const delivery = selectField(t('Delivery','投递方式'),[
    ['none',t('None','无')], ['announce',t('Announce','会话通知')], ['webhook','Webhook']
  ]);
  delivery.lastElementChild.disabled = true;
  const timeout = input(t('Timeout in seconds','超时秒数'),{type:'number',required:true,min:1});
  const retries = input(t('Maximum retries','最大重试次数'),{type:'number',required:true,min:0});
  const deleteAfter = input(t('Delete after success','成功后删除'),{type:'checkbox'});
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
    payloadType.value = row?.payload_kind ?? 'system_event';
    actionText.value = row?.action_text ?? '';
    conversation.value = row?.conversation_mode ?? 'reuse';
    delivery.value = row?.delivery_kind ?? 'none';
    timeout.value = String(row?.timeout_seconds ?? 300);
    retries.value = String(row?.max_retries ?? 3);
    deleteAfter.checked = row?.delete_after_run ?? false;
    remove.disabled = !row || !scope.commands.includes('delete-schedule');
    confirmRemoval.hidden = cancelRemoval.hidden = true;
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
    if (![name, description, interval, instant, expression, zone, timeout, retries].every(control => control.reportValidity())) return;
    const row = current();
    const payload = {name:name.value, enabled:enabled.checked, description:description.value,
      ...(row && {job_id:row.id, expected_revision:row.revision})};
    if (!row || payloadType.value !== row.payload_kind || actionText.value !== (row.action_text ?? '')) {
      payload.action = {kind: payloadType.value, text: actionText.value || name.value};
    }
    if (delivery.value !== (row?.delivery_kind ?? 'none')) payload.delivery_kind = delivery.value;
    Object.assign(payload,{conversation_mode:conversation.value, timeout_seconds:timeout.valueAsNumber,
      max_retries:retries.valueAsNumber,delete_after_run:deleteAfter.checked});
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
  const remove = action(t('Delete schedule','删除计划任务'), () => {
    confirmRemoval.hidden = cancelRemoval.hidden = false;
    status.textContent = t('Delete this schedule?','确认删除此计划任务？') + ' ' + current().name;
  });
  const cancelRemoval = action(t('Cancel deletion','取消删除'), () => {
    confirmRemoval.hidden = cancelRemoval.hidden = true;
    status.textContent = '';
  });
  const confirmRemoval = action(t('Confirm deletion','确认删除'), async () => {
    const row = current();
    if (!row) return;
    await mutate('delete-schedule',{job_id:row.id,expected_revision:row.revision});
    await load();
    status.textContent = t('Schedule deleted','计划任务已删除');
  });
  confirmRemoval.hidden = cancelRemoval.hidden = true;
  remove.disabled = true;
  const previous = action(t('Previous page','上一页'), async () => {offset = Math.max(0,offset-32); await load();});
  const next = action(t('Next page','下一页'), async () => {offset += 32; await load();});
  const refresh = action(t('Refresh','刷新'), () => load(job.value));
  kind.onchange = showTrigger;
  job.onchange = select;
  previous.disabled = next.disabled = run.disabled = showHistory.disabled = save.disabled = true;
  document.getElementById('root').append(title, panel, status, history);
  refresh.click();
})();

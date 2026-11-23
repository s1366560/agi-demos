(async () => {
  const api = window.memstack;
  const { locale } = await api.scope();
  const t = (en, zh) => locale.startsWith('zh') ? zh : en;
  const root = document.getElementById('root');
  const node = (tag, text) => Object.assign(document.createElement(tag), {textContent: text});
  const title = node('h1', t('Project schedules', '项目计划任务'));
  const panel = document.createElement('fieldset');
  const job = document.createElement('select');
  const name = document.createElement('input');
  name.required = true;
  name.maxLength = 255;
  const interval = Object.assign(document.createElement('input'), {type:'number', min:'1', max:'31536000', value:'60', required:true});
  const enabled = Object.assign(document.createElement('input'), {type:'checkbox'});
  function field(label, input) {
    const caption = node('label', label);
    caption.append(input);
    panel.append(caption);
  }
  field(t('Schedule', '计划任务'), job);
  field(t('Name', '名称'), name);
  field(t('Interval in seconds', '间隔秒数'), interval);
  field(t('Run on schedule', '启用定时运行'), enabled);
  const status = node('p','');
  status.setAttribute('role','status');
  let rows = [], offset = 0, total = 0;
  const attempts = new Map();
  function key(operation, data) {
    const request = JSON.stringify([operation,data]);
    if (!attempts.has(request)) attempts.set(request, Array.from(crypto.getRandomValues(new Uint32Array(4)), n => n.toString(16).padStart(8,'0')).join(''));
    return attempts.get(request);
  }
  function action(text, fn) {
    const button = node('button',text);
    button.type = 'button';
    button.onclick = async () => {
      panel.disabled = true;
      try { await fn(); } catch (error) { status.textContent = String(error); }
      finally { panel.disabled = false; }
    };
    panel.append(button);
    return button;
  }
  function select() {
    const row = rows.find(item => item.id === job.value);
    name.value = row?.name || '';
    interval.value = String(row?.interval_seconds ?? 60);
    enabled.checked = row?.enabled ?? false;
    run.disabled = !row;
    save.disabled = !!row && row.interval_seconds == null;
  }
  async function load(id) {
    const result = await api.invoke('list-schedules',{offset});
    rows = result.items;
    total = result.total;
    job.replaceChildren(new Option(t('New schedule','新建计划任务'),''));
    for (const row of rows) job.add(new Option(row.name,row.id));
    job.value = rows.some(item => item.id === id) ? id : '';
    select();
    previous.disabled = offset === 0;
    next.disabled = offset + rows.length >= total;
  }
  const save = action(t('Save schedule','保存计划任务'), async () => {
    if (!name.reportValidity() || !interval.reportValidity()) return;
    const row = rows.find(item => item.id === job.value);
    const input = {name:name.value, interval_seconds:interval.valueAsNumber, enabled:enabled.checked,
      ...(row ? {job_id:row.id,expected_revision:row.revision} : {})};
    const result = await api.invoke('save-schedule', {...input,idempotency_key:key('save',input)});
    await load(result.id);
    status.textContent = t('Schedule saved','计划任务已保存');
  });
  const run = action(t('Run now','立即运行'), async () => {
    const row = rows.find(item => item.id === job.value);
    if (!row) return;
    const input = {job_id:row.id,expected_revision:row.revision};
    const request = JSON.stringify(['run',input]);
    const receipt = await api.invoke('run-schedule', {...input,idempotency_key:key('run',input)});
    attempts.delete(request);
    status.textContent = receipt.status + ' · ' + receipt.run_id;
  });
  const previous = action(t('Previous page','上一页'), async () => {offset = Math.max(0,offset-32); await load();});
  const next = action(t('Next page','下一页'), async () => {offset += 32; await load();});
  const refresh = action(t('Refresh','刷新'), () => load(job.value));
  job.onchange = select;
  run.disabled = previous.disabled = next.disabled = true;
  root.append(title,panel,status);
  refresh.click();
})();

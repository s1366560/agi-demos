(async () => {
  const sdk = window.memstack;
  const scope = await sdk.getContext();
  const parts = scope.pathname.split('?')[0].split('/').filter(Boolean);
  const workspace = decodeURIComponent(parts.at(-2));
  const topic = parts.at(-1);
  const t = (en, zh) => scope.locale.startsWith('zh') ? zh : en;
  const members = topic === 'members';
  const posts = topic === 'posts';
  const name = members ? t('Members', '成员') : posts ? t('Blackboard posts', '黑板帖子') : t('Tasks', '任务');
  const node = (tag, text) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const root = document.getElementById('root');
  const status = node('p');
  status.setAttribute('role', 'status');
  const back = node('a', t('Workspace details', '工作区详情'));
  back.href = '/' + parts.slice(0, -1).join('/');
  back.onclick = (event) => { event.preventDefault(); void sdk.navigate(back.getAttribute('href')); };
  const list = node('ul');
  const form = node('form');
  const controls = node('fieldset');
  const addField = (label, input) => {
    const field = node('label', label);
    field.append(input);
    controls.append(field);
    return input;
  };
  const title = addField(members ? t('User ID', '用户 ID') : t('Title', '标题'), node('input'));
  title.required = true;
  title.maxLength = members ? 128 : 255;
  const content = members ? addField(t('Role', '角色'), node('select')) :
    addField(posts ? t('Content', '正文') : t('Description', '描述'), node('textarea'));
  if (members) {
    for (const [id, label] of [['viewer', t('Viewer', '查看者')], ['editor', t('Editor', '编辑者')], ['owner', t('Owner', '所有者')]]) content.add(new Option(label, id));
  } else {
    content.required = posts;
    content.maxLength = 65536;
  }
  const lifecycle = members ? null : addField(t('Status', '状态'), node('select'));
  if (lifecycle) {
    const options = posts ? [['open', t('Open', '开放')], ['archived', t('Archived', '已归档')]] :
      [['todo', t('To do', '待处理')], ['in_progress', t('In progress', '进行中')], ['blocked', t('Blocked', '已阻塞')], ['done', t('Done', '已完成')]];
    options.forEach(([value, label]) => lifecycle.add(new Option(label, value)));
    lifecycle.disabled = !posts;
  }
  const pinned = posts ? addField(t('Pinned', '置顶'), node('input')) : null;
  if (pinned) pinned.type = 'checkbox';
  const button = (label, fn) => {
    const b = node('button', label);
    b.type = 'button';
    b.onclick = fn;
    return b;
  };
  let selected = null;
  let revision;
  let offset = 0;
  const limit = 25;
  let pending = false;
  const save = node('button', t('Add', '添加'));
  save.type = 'button';
  const cancel = button(t('Cancel', '取消'), reset);
  cancel.hidden = true;
  function reset() {
    selected = null;
    form.reset();
    title.disabled = false;
    if (lifecycle) lifecycle.disabled = !posts;
    cancel.hidden = true;
    save.textContent = t('Add', '添加');
  }
  controls.append(save, cancel);
  form.append(controls);
  root.append(back, node('h1', name), status, form, list);
  const prev = button(t('Previous page', '上一页'), () => load(offset - limit));
  const next = button(t('Next page', '下一页'), () => load(offset + limit));
  root.append(prev, next, button(t('Refresh', '刷新'), () => { if (!pending) void load(); }));
  async function load(position = offset) {
    list.replaceChildren();
    controls.disabled = prev.disabled = next.disabled = true;
    try {
      const info = await sdk.invoke('read-workspace', {workspace_id: workspace, include_revision: true});
      const page = await sdk.invoke('list-' + topic, {workspace_id: workspace, limit, offset: position});
      revision = info.revision;
      offset = position;
      controls.disabled = false;
      prev.disabled = offset === 0;
      next.disabled = page.items.length < limit;
      status.textContent = page.items.length ? '' : t('No entries', '暂无记录');
      for (const row of page.items) {
        const item = node('li');
        const label = members ? row.user_email || row.user_id : row.title;
        item.append(node('strong', label), node('p', members ? row.role : (row.content || row.description || '')));
        if (lifecycle) {
          const stateLabel = Array.from(lifecycle.options).find(option => option.value === row.status);
          item.append(node('p', [stateLabel?.text || row.status, row.is_pinned && t('Pinned', '置顶')].filter(Boolean).join(' · ')));
        }
        item.append(button(t('Edit', '编辑'), () => {
          if (pending) return;
          selected = members ? row.user_id : row.id;
          title.value = members ? row.user_id : row.title;
          title.disabled = members;
          content.value = members ? row.role : (row.content || row.description || '');
          if (lifecycle) {
            lifecycle.value = row.status;
            lifecycle.disabled = !lifecycle.value;
          }
          if (pinned) pinned.checked = row.is_pinned;
          cancel.hidden = false;
          save.textContent = t('Save', '保存');
          (members ? content : title).focus();
        }));
        const remove = button(t('Remove', '移除'), () => {
          if (pending || item.querySelector('fieldset')) return;
          const confirm = node('fieldset');
          confirm.append(node('legend', t('Remove this entry?', '确认移除此记录？')),
            button(t('Confirm removal', '确认移除'), () => change('delete', members ? row.user_id : row.id, {})),
            button(t('Cancel', '取消'), () => confirm.remove()));
          item.append(confirm);
        });
        item.append(remove);
        list.append(item);
      }
    } catch (error) { status.textContent = error.message; }
  }
  let intent;
  let previous;
  async function change(action, id, fields) {
    if (pending) return;
    pending = true;
    controls.disabled = true;
    try {
      const data = {workspace_id: workspace, expected_revision: revision, action, id, fields};
      const key = JSON.stringify(data);
      if (key !== previous) { intent = crypto.randomUUID(); previous = key; }
      await sdk.invoke('change-' + topic, {...data, request_id: intent});
      intent = previous = undefined;
      reset();
      await load();
    } catch (error) { status.textContent = error.message; }
    finally { pending = false; controls.disabled = false; }
  }
  save.onclick = () => {
    if (!form.reportValidity()) return;
    const fields = members ? {role: content.value, ...(selected ? {} : {user_id: title.value})}
      : {title: title.value, [posts ? 'content' : 'description']: content.value};
    if (lifecycle && !lifecycle.disabled) fields.status = lifecycle.value;
    if (pinned) fields.is_pinned = pinned.checked;
    void change(selected ? 'update' : 'create', selected, fields);
  };
  form.onsubmit = (event) => { event.preventDefault(); save.click(); };
  form.onkeydown = (event) => {
    if (event.key === 'Enter' && event.target.tagName === 'INPUT') {
      event.preventDefault();
      save.click();
    }
  };
  await load();
})();

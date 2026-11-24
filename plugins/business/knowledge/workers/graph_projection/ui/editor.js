(async () => {
  const sdk = window.memstack;
  const scope = await sdk.getContext();
  const t = (en, zh) => scope.locale.startsWith('zh') ? zh : en;
  const project = '/tenant/' + encodeURIComponent(scope.tenantId) + '/project/' + encodeURIComponent(scope.projectId);
  const match = scope.pathname.match(/\/memory\/([^/]+)\/?$/);
  const id = match && decodeURIComponent(match[1]);
  function element(tag, text) {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    return node;
  }
  const root = document.getElementById('root');
  const back = element('button', t('Project memories', '项目记忆'));
  const heading = element('h1', id ? t('Memory details', '记忆详情') : t('New memory', '新建记忆'));
  const status = element('p');
  status.setAttribute('role', 'status');
  const form = element('form');
  const fields = element('fieldset');
  const titleLabel = element('label', t('Title', '标题'));
  const title = element('input');
  title.required = true;
  title.maxLength = 500;
  titleLabel.append(title);
  const contentLabel = element('label', t('Content', '正文'));
  const content = element('textarea');
  content.required = true;
  content.rows = 12;
  content.maxLength = 32768;
  contentLabel.append(content);
  const revision = element('p');
  const save = element('button', t('Save memory', '保存记忆'));
  save.type = 'button';
  const reload = element('button', t('Reload saved version', '重新读取已保存版本'));
  reload.type = 'button';
  fields.append(titleLabel, contentLabel, save);
  form.append(fields);
  root.append(back, heading, revision, form, status);
  if (id) root.append(reload);
  let version = 0;
  let memoryId = id;
  let changeId;
  function show(memory) {
    version = memory.version;
    memoryId = memory.id;
    title.value = memory.title;
    content.value = memory.content;
    revision.textContent = t('Version ', '版本 ') + version + ' · ' + memory.processing_status;
  }
  async function load() {
    fields.disabled = true;
    reload.disabled = true;
    try {
      show(await sdk.invoke('read-memory', {id: memoryId}));
      fields.disabled = !scope.commands.includes('save-memory');
      status.textContent = '';
    } catch (error) {
      status.textContent = String(error);
    } finally {
      reload.disabled = false;
    }
  }
  back.onclick = () => sdk.navigate(project + '/memories').catch(error => status.textContent = String(error));
  reload.onclick = load;
  form.oninput = () => { changeId = undefined; };
  title.onkeydown = event => {
    if (event.key === 'Enter' && !event.isComposing) {
      event.preventDefault();
      save.click();
    }
  };
  save.onclick = async () => {
    if (fields.disabled || !form.reportValidity()) return;
    fields.disabled = true;
    reload.disabled = true;
    try {
      changeId ??= crypto.randomUUID();
      const result = await sdk.invoke('save-memory', {
        ...(memoryId ? {id: memoryId} : {}), version, change_id: changeId, title: title.value, content: content.value,
      });
      show(result);
      changeId = undefined;
      status.textContent = t('Memory saved.', '记忆已保存。');
      if (!id) await sdk.navigate(project + '/memory/' + encodeURIComponent(result.id));
    } catch (error) {
      status.textContent = String(error);
    } finally {
      fields.disabled = false;
      reload.disabled = false;
    }
  };
  if (id) await load();
})();

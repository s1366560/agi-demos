(async () => {
  const sdk = window.memstack;
  const scope = await sdk.getContext();
  const t = (en, zh) => scope.locale.startsWith('zh') ? zh : en;
  const root = document.getElementById('root');
  const node = (tag, text = '') => {
    const element = document.createElement(tag);
    element.textContent = text;
    return element;
  };
  const directory = '/tenant/' + encodeURIComponent(scope.tenantId) + '/project/' +
    encodeURIComponent(scope.projectId) + '/workspaces';
  const parts = scope.pathname.split('/').filter(Boolean);
  const id = decodeURIComponent(parts.at(-2));
  const status = node('p');
  status.setAttribute('role', 'status');
  const backlink = node('a', t('Workspace directory', '工作区目录'));
  backlink.href = directory;
  backlink.onclick = event => {
    event.preventDefault();
    sdk.navigate(directory).catch(error => { status.textContent = error.message; });
  };
  root.append(backlink, node('h1', t('Workspace settings', '工作区设置')), status);

  const form = node('form');
  const field = (caption, control) => {
    const label = node('label', caption);
    label.append(control);
    form.append(label);
    return control;
  };
  const name = field(t('Workspace name', '工作区名称'), node('input'));
  name.required = true;
  name.maxLength = 255;
  const description = field(t('Description', '描述'), node('textarea'));
  description.rows = 4;
  description.maxLength = 65536;
  let revision;
  const archived = field(t('Archived', '已归档'), node('input'));
  archived.type = 'checkbox';
  async function loadSettings() {
    const info = await sdk.invoke('read-workspace', {workspace_id: id, include_revision: true});
    revision = info.revision;
    name.value = info.name;
    description.value = info.description ?? '';
    archived.checked = info.is_archived;
    status.textContent = '';
  }
  const reload = node('button', t('Reload settings', '重新读取设置'));
  reload.type = 'button';
  reload.onclick = () => loadSettings().catch(error => { status.textContent = error.message; });
  form.append(reload);
  try { await loadSettings(); } catch (error) { status.textContent = error.message; return; }

  const submit = node('button', t('Save changes', '保存更改'));
  submit.type = 'button';
  form.append(submit);
  root.append(form);
  let previousBody;
  let intent;
  form.addEventListener('keydown', event => {
    if (event.key === 'Enter' && event.target instanceof HTMLInputElement && event.target.type !== 'checkbox') {
      event.preventDefault();
      submit.click();
    }
  });
  submit.onclick = async () => {
    if (submit.disabled || !form.reportValidity()) return;
    submit.disabled = true;
    status.textContent = '';
    try {
      if (!name.value.trim()) {
        throw new Error(t('Enter a workspace name.', '请输入工作区名称。'));
      }
      const body = {name: name.value.trim(), description: description.value.trim(),
        workspace_id: id, expected_revision: revision, is_archived: archived.checked};
      const content = JSON.stringify(body);
      if (content !== previousBody) {
        intent = crypto.randomUUID();
        previousBody = content;
      }
      const result = await sdk.invoke('update-workspace', {...body, request_id: intent});
      await sdk.navigate(directory + '/' + encodeURIComponent(result.id));
    } catch (error) { status.textContent = error.message; }
    finally { submit.disabled = false; }
  };
})();

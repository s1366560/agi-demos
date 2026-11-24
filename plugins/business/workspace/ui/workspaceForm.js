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
  const creating = parts.at(-1) === 'new';
  const id = creating ? null : decodeURIComponent(parts.at(-2));
  const status = node('p');
  status.setAttribute('role', 'status');
  const backlink = node('a', t('Workspace directory', '工作区目录'));
  backlink.href = directory;
  backlink.onclick = event => {
    event.preventDefault();
    sdk.navigate(directory).catch(error => { status.textContent = error.message; });
  };
  root.append(backlink, node('h1', creating ? t('Create workspace', '创建工作区') : t('Workspace settings', '工作区设置')), status);

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
  const select = (caption, options) => {
    const input = field(caption, node('select'));
    input.required = true;
    input.append(new Option(t('Select…', '请选择…'), ''));
    for (const [value, text] of options) input.append(new Option(text, value));
    return input;
  };
  let createOptions;
  let archived;
  let revision;
  if (creating) {
    description.required = true;
    description.minLength = 12;
    const useCase = select(t('Use case', '使用场景'), [
      ['general', t('General', '通用')], ['programming', t('Programming', '软件开发')],
      ['conversation', t('Conversation', '会话')], ['operations', t('Operations', '运营')],
      ['research', t('Research', '研究')],
    ]);
    const mode = select(t('Collaboration mode', '协作模式'), [
      ['single_agent', t('Single agent', '单智能体')],
      ['multi_agent_shared', t('Shared conversation', '多智能体共享会话')],
      ['multi_agent_isolated', t('Isolated conversations', '多智能体独立会话')],
      ['autonomous', t('Autonomous', '自主协作')],
    ]);
    const codeRoot = field(t('Sandbox code directory', '沙箱代码目录'), node('input'));
    codeRoot.parentElement.hidden = true;
    codeRoot.placeholder = '/workspace/repository';
    useCase.onchange = () => {
      codeRoot.required = useCase.value === 'programming';
      codeRoot.parentElement.hidden = !codeRoot.required;
    };
    createOptions = () => {
      const category = useCase.value;
      const workspaceType = {programming: 'software_development', research: 'research', operations: 'operations'}[category] ?? 'general';
      const metadata = { workspace_use_case: category, workspace_type: workspaceType, collaboration_mode: mode.value, agent_conversation_mode: mode.value, autonomy_profile: {workspace_type: workspaceType} };
      const data = {use_case: category, collaboration_mode: mode.value, metadata};
      if (category === 'programming') {
        let path = codeRoot.value.trim().replace(/\/+$/, '');
        if (!path.startsWith('/')) path = '/workspace/' + path;
        if (!path.startsWith('/workspace/') || path.split('/').some(part => part === '..' || part === '.') || path === '/workspace/') {
          throw new Error(t('Choose a directory inside /workspace.', '请选择 /workspace 下的目录。'));
        }
        data.sandbox_code_root = path;
        metadata.sandbox_code_root = path;
        metadata.code_context = {sandbox_code_root: path};
      }
      return data;
    };
  } else {
    archived = field(t('Archived', '已归档'), node('input'));
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
  }

  const submit = node('button', creating ? t('Create workspace', '创建工作区') : t('Save changes', '保存更改'));
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
      if (!name.value.trim() || (creating && description.value.trim().length < 12)) {
        throw new Error(t('Enter a name and a description of at least 12 characters.', '请输入名称和至少 12 个字符的描述。'));
      }
      const body = {name: name.value.trim(), description: description.value.trim(),
        ...(creating ? createOptions() : {workspace_id: id, expected_revision: revision, is_archived: archived.checked})};
      const content = JSON.stringify(body);
      if (content !== previousBody) {
        intent = crypto.randomUUID();
        previousBody = content;
      }
      const result = await sdk.invoke(creating ? 'create-workspace' : 'update-workspace', {...body, request_id: intent});
      await sdk.navigate(directory + '/' + encodeURIComponent(result.id));
    } catch (error) { status.textContent = error.message; }
    finally { submit.disabled = false; }
  };
})();

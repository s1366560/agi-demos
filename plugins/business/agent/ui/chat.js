(async () => {
  const sdk = window.memstack;
  const ctx = await sdk.getContext();
  const t = (en, zh) => ctx.locale.startsWith('zh') ? zh : en;
  const desktop = ctx.platform === 'desktop-renderer';
  const hasLocalChat = desktop && ctx.deviceTools.includes('local_chat');
  const root = document.getElementById('root');
  function element(tag, text) {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    return node;
  }
  const select = element('select');
  select.setAttribute('aria-label', t('Conversation', '会话'));
  const newTarget = element('select');
  newTarget.setAttribute('aria-label', t('New conversation location', '新会话执行位置'));
  newTarget.append(new Option(t('This device', '本机'), 'local'), new Option(t('Cloud', '云端'), 'cloud'));
  newTarget.hidden = !desktop;
  const refresh = element('button', t('Reload history', '刷新历史'));
  const create = element('button', t('New conversation', '新会话'));
  const title = element('input');
  title.maxLength = 500;
  title.setAttribute('aria-label', t('Conversation title', '会话标题'));
  const rename = element('button', t('Rename conversation', '重命名会话'));
  const older = element('button', t('Earlier messages', '更早的消息'));
  older.hidden = true;
  const transcript = element('ol');
  const draft = element('textarea');
  draft.setAttribute('aria-label', t('Message', '消息'));
  draft.maxLength = 32000;
  const send = element('button');
  const stop = element('button', t('Cancel run', '取消运行'));
  const placement = element('p');
  const status = element('p');
  status.setAttribute('role', 'status');
  root.append(element('h1', t('Agent chat', '智能体对话')), select, newTarget, create, title, rename, refresh,
    older, transcript, placement, draft, send, stop, status);

  let active = false;
  let stopping = false;
  let run;
  let pendingDevice;
  let historyVersion = 0;
  let before;
  const link = ctx.pathname.match(/\/agent-workspace\/([^/]+)\/?$/);
  const target = () => select.selectedOptions[0]?.dataset.target;
  function controls() {
    const local = target() === 'local';
    const writable = target() === 'cloud' || (local && hasLocalChat);
    select.disabled = newTarget.disabled = create.disabled = refresh.disabled = active;
    title.disabled = !select.value || active;
    rename.disabled = title.disabled || !title.value.trim() || title.value.trim() === select.selectedOptions[0]?.text;
    draft.readOnly = !writable || active;
    send.textContent = local ? t('Send to device', '发送到本机') : t('Send to cloud', '发送到云端');
    send.disabled = !writable || active || !draft.value.trim();
    stop.disabled = !run || stopping;
    if (local && !desktop) {
      placement.textContent = t('Device conversation. Open the desktop app to send a message.', '本机会话。请打开桌面应用发送消息。');
    } else if (local && !hasLocalChat) {
      placement.textContent = t('This Agent release has no local chat capability.', '当前 Agent 版本未提供本机对话能力。');
    } else {
      placement.textContent = local
        ? t('Runs in the workspace selected in device settings.', '在设备设置选定的工作目录中运行。')
        : '';
    }
  }
  async function history(previous = false) {
    const version = ++historyVersion;
    if (!previous) { transcript.replaceChildren(); before = undefined; }
    older.hidden = true;
    if (!previous) title.value = select.selectedOptions[0]?.text ?? '';
    controls();
    if (!select.value) return;
    const result = await sdk.invoke('chat-history', {conversation_id: select.value, ...(previous ? before : {})});
    if (version !== historyVersion) return;
    const messages = result.messages.map(row => element('li', row.content));
    if (previous) transcript.prepend(...messages);
    else transcript.append(...messages);
    before = result.before;
    older.hidden = !before;
  }
  function report(error) {
    const message = error instanceof Error ? error.message : String(error);
    if (message.includes('device_local_workspace_required')) {
      status.textContent = t('Choose a workspace in device settings before sending.', '请先在设备设置中选择工作目录。');
    } else if (message.includes('device_plugin_installation_required') || message.includes('device_plugin_grant_')) {
      status.textContent = t('Approve this Agent release in device settings. ', '请在设备设置中批准当前 Agent 版本。') + message;
    } else {
      status.textContent = message;
    }
  }
  async function conversations(preferred) {
    const result = await sdk.invoke('chat-list', {});
    select.replaceChildren(...result.items.map(row => {
      const option = new Option(row.title, row.id);
      option.dataset.target = row.execution_target;
      return option;
    }));
    if (preferred && !Array.from(select.options).some(item => item.value === preferred)) {
      select.append(new Option(preferred, preferred));
    }
    if (preferred) select.value = preferred;
    controls();
    await history();
  }
  create.onclick = async () => {
    active = true;
    status.textContent = '';
    controls();
    try {
      const row = await sdk.invoke('chat-create', {
        title: t('New conversation', '新会话'),
        ...(desktop && newTarget.value === 'local' ? { execution_target: 'local' } : {}),
      });
      await conversations(row.id);
    } catch (error) { report(error); }
    finally { active = false; controls(); }
  };
  title.oninput = controls;
  rename.onclick = async () => {
    if (rename.disabled) return;
    active = true;
    controls();
    try {
      const row = await sdk.invoke('chat-rename', { conversation_id: select.value, title: title.value.trim() });
      select.selectedOptions[0].text = title.value = row.title;
    } catch (error) { report(error); }
    finally { active = false; controls(); }
  };
  older.onclick = () => history(true).catch(report);
  refresh.onclick = select.onchange = () => { status.textContent = ''; controls(); history().catch(report); };
  draft.oninput = controls;

  stop.onclick = async () => {
    if (!run || stopping) return;
    const current = run;
    stopping = true;
    controls();
    try {
      const result = current.target === 'local'
        ? await sdk.device('local_chat', { action: 'stop', ...current.binding })
        : await sdk.invoke('chat-cancel', {conversation_id: current.conversation_id, run_id: current.run_id, expected_revision: current.revision});
      if (run === current) status.textContent = result.status;
    } catch (error) { if (run === current) report(error); }
    finally { if (run === current) { stopping = false; controls(); } }
  };

  async function localTurn(conversation, text) {
    if (pendingDevice?.conversation !== conversation || pendingDevice.text !== text) {
      pendingDevice = { conversation, text, key: crypto.randomUUID() };
    }
    const binding = { conversation_id: conversation, idempotency_key: pendingDevice.key };
    run = { target: 'local', binding };
    controls();
    status.textContent = t('Waiting for this device…', '正在等待本机执行…');
    const result = await sdk.device('local_chat', { action: 'execute', ...binding, message: text });
    status.textContent = [result.status, result.sync, result.detail].filter(Boolean).join(' · ');
    if (result.executed || result.sync === 'synced' || result.status === 'cancelled') {
      pendingDevice = undefined;
      draft.value = '';
    }
    await history();
  }
  async function cloudTurn(conversation, text) {
    const answer = element('li');
    transcript.append(element('li', text), answer);
    await sdk.invoke('chat-turn', {conversation_id: conversation, message: text, message_id: crypto.randomUUID()}, {
      onEvent(event) {
        if (event.type === 'accepted') {
          run = { target: 'cloud', conversation_id: conversation, run_id: event.run_id, revision: event.revision };
          draft.value = '';
          controls();
        } else if (event.type === 'text_delta') answer.textContent += event.text;
        else if (event.type === 'assistant_message') answer.textContent = event.text;
      },
    });
    await history();
  }
  send.onclick = async () => {
    if (send.disabled) return;
    active = true;
    controls();
    status.textContent = '';
    try {
      if (target() === 'local') await localTurn(select.value, draft.value);
      else await cloudTurn(select.value, draft.value);
    } catch (error) { report(error); }
    finally { run = undefined; stopping = active = false; controls(); }
  };
  controls();
  await conversations(link && link[1]).catch(report);
})();

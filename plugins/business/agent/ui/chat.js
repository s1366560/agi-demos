(async () => {
  const sdk = window.memstack;
  const ctx = await sdk.getContext();
  const localize = (en, zh) => ctx.locale.startsWith('zh') ? zh : en;
  const root = document.getElementById('root');
  function element(tag, text) {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    return node;
  }
  const select = element('select');
  select.setAttribute('aria-label', localize('Conversation', '会话'));
  const refresh = element('button', localize('Reload history', '刷新历史'));
  const create = element('button', localize('New conversation', '新会话'));
  const older = element('button', localize('Earlier messages', '更早的消息'));
  older.hidden = true;
  const transcript = element('ol');
  const draft = element('textarea');
  draft.setAttribute('aria-label', localize('Message', '消息'));
  draft.maxLength = 32000;
  const send = element('button', localize('Send to cloud', '发送到云端'));
  const stop = element('button', localize('Cancel run', '取消运行'));
  const status = element('p');
  status.setAttribute('role', 'status');
  root.append(element('h1', localize('Cloud chat', '云端对话')), select, create, refresh, older, transcript, draft, send, stop, status);
  let active = false;
  let run;
  let historyVersion = 0;
  const link = ctx.pathname.match(/\/agent-workspace\/([^/]+)\/?$/);
  function controls() {
    select.disabled = create.disabled = refresh.disabled = active;
    send.disabled = select.selectedOptions[0]?.dataset.target === 'local' || active || !select.value || !draft.value.trim();
    stop.disabled = !run;
  }
  let before;
  async function history(previous = false) {
    const version = ++historyVersion;
    if (!previous) { transcript.replaceChildren(); before = undefined; }
    older.hidden = true;
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
    status.textContent = String(error);
  }
  async function conversations(preferred) {
    const result = await sdk.invoke('chat-list', {});
    select.replaceChildren(...result.items.map(row => {
      const option = element('option', row.title);
      option.value = row.id;
      option.dataset.target = row.execution_target;
      return option;
    }));
    if (preferred && !Array.from(select.options).some(item => item.value === preferred)) {
      const option = element('option', preferred);
      option.value = preferred;
      select.append(option);
    }
    if (preferred) select.value = preferred;
    controls();
    await history();
  }
  create.onclick = async () => {
    try {
      const row = await sdk.invoke('chat-create', {title: localize('New conversation', '新会话')});
      await conversations(row.id);
    } catch (error) { report(error); }
  };
  older.onclick = () => history(true).catch(report);
  refresh.onclick = select.onchange = () => { controls(); history().catch(report); };
  draft.oninput = controls;
  stop.onclick = async () => {
    if (!run) return;
    try {
      const result = await sdk.invoke('chat-cancel', {conversation_id: select.value, run_id: run.run_id, expected_revision: run.revision});
      status.textContent = result.status;
    } catch (error) { report(error); }
  };
  send.onclick = async () => {
    if (active || !select.value || !draft.value.trim()) return;
    active = true;
    controls();
    status.textContent = '';
    const text = draft.value;
    const answer = element('li');
    transcript.append(element('li', text), answer);
    try {
      await sdk.invoke('chat-turn', {conversation_id: select.value, message: text, message_id: crypto.randomUUID()}, {
        onEvent(event) {
          if (event.type === 'accepted') {
            run = event;
            draft.value = '';
            controls();
          } else if (event.type === 'text_delta') answer.textContent += event.text;
          else if (event.type === 'assistant_message') answer.textContent = event.text;
        },
      });
      await history();
    } catch (error) { report(error); }
    finally { run = undefined; active = false; controls(); }
  };
  controls();
  await conversations(link && link[1]).catch(report);
})();

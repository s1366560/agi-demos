(async () => {
  const sdk = window.memstack;
  const scope = await sdk.getContext();
  const root = document.getElementById('root');
  const t = (en, zh) => scope.locale.startsWith('zh') ? zh : en;
  const node = (tag, text) => {
    const value = document.createElement(tag);
    value.textContent = text;
    return value;
  };
  const status = node('p', '');
  status.setAttribute('role', 'status');
  const base = '/tenant/' + encodeURIComponent(scope.tenantId) + '/project/' + encodeURIComponent(scope.projectId);
  const link = (text, path) => {
    const a = node('a', text);
    a.href = path;
    a.onclick = event => {
      event.preventDefault();
      sdk.navigate(path).catch(error => status.textContent = String(error));
    };
    return a;
  };
  const match = /\/workspaces\/([^/]+)\/?$/.exec(scope.pathname);
  try {
    if (match) {
      root.append(link(t('Project overview', '项目概览'), base), status);
      const info = await sdk.invoke('read-workspace', {workspace_id: decodeURIComponent(match[1])});
      root.append(node('h1', info.name));
      if (info.description) root.append(node('p', info.description));
      const fields = node('dl', '');
      for (const [label, value] of [
        [t('Workspace ID', '工作区 ID'), info.id],
        [t('Status', '状态'), info.office_status],
        [t('Archived', '已归档'), info.is_archived ? t('Yes','是') : t('No','否')],
      ]) fields.append(node('dt', label), node('dd', value));
      root.append(fields, link(t('Workspace settings', '工作区设置'), base + '/workspaces/' + encodeURIComponent(info.id) + '/settings'));
      for (const [path, title] of [['members', t('Members', '成员')], ['posts', t('Blackboard posts', '黑板帖子')], ['tasks', t('Tasks', '任务')]]) {
        root.append(link(title, base + '/workspaces/' + encodeURIComponent(info.id) + '/' + path));
      }
      return;
    }
    root.append(node('h1', t('Project overview', '项目概览')), node('p', scope.projectId),
      node('h2', t('Your workspaces', '我可访问的工作区')));
    const list = node('ul', '');
    const more = node('button', t('Load more', '加载更多'));
    more.type = 'button';
    root.append(list, more, status, link(t('Create workspace', '创建工作区'), base + '/workspaces/new'), link(t('Directory and CSV export', '目录与 CSV 导出'), base + '/workspaces'));
    let offset = 0;
    async function load() {
      more.disabled = true;
      try {
        const page = await sdk.invoke('list-directory', {limit: 8, offset});
        for (const item of page.rows) {
          const row = node('li', '');
          row.append(link(item.name, base + '/workspaces/' + encodeURIComponent(item.id)));
          row.append(node('span', ' · ' + (item.is_archived ? t('Archived', '已归档') : item.office_status)));
          list.append(row);
        }
        offset += page.rows.length;
        more.hidden = page.rows.length < 8;
        status.textContent = offset ? '' : t('No accessible workspaces in this project.', '当前项目没有可访问的工作区。');
      } catch (error) { status.textContent = String(error); }
      finally { more.disabled = false; }
    }
    more.onclick = load;
    await load();
  } catch (error) { status.textContent = String(error); }
})();

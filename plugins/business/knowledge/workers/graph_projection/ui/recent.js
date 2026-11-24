(async () => {
  const sdk = window.memstack;
  const { locale, tenantId, projectId } = await sdk.scope();
  const zh = locale.startsWith('zh');
  const root = document.getElementById('root');
  const heading = document.createElement('h2');
  heading.textContent = zh ? '最近记忆' : 'Recent memories';
  root.append(heading);
  const status = document.createElement('p');
  status.setAttribute('role', 'status');
  root.append(status);
  try {
    const { items } = await sdk.invoke('list-memories', { limit: 5 });
    const list = document.createElement('ul');
    for (const memory of items) {
      const row = document.createElement('li');
      const link = document.createElement('button');
      link.textContent = memory.title || memory.excerpt || memory.id;
      link.onclick = () => sdk.navigate('/tenant/' + encodeURIComponent(tenantId) +
        '/project/' + encodeURIComponent(projectId) + '/memory/' + encodeURIComponent(memory.id))
        .catch((error) => { status.textContent = String(error); });
      row.append(link);
      list.append(row);
    }
    root.append(list);
    if (!items.length) status.textContent = zh ? '暂无记忆' : 'No memories yet';
  } catch (error) { status.textContent = String(error); }
})();

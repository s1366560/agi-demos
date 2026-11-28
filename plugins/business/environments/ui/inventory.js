(async () => {
  const { locale, tenantId, pathname } = await window.memstack.scope();
  const zh = locale.startsWith('zh');
  const label = (en, cn) => zh ? cn : en;
  const parts = pathname.split('/');
  const index = parts[3] === 'environments' ? 4 : 3;
  const kind = parts[index];
  const id = parts[index + 1] ? decodeURIComponent(parts[index + 1]) : null;
  const base = '/tenant/' + encodeURIComponent(tenantId) + '/environments/' + kind;
  const title = kind === 'clusters' ? label('Clusters', '集群') : label('Instances', '实例');
  function node(tag, value) {
    const el = document.createElement(tag);
    if (value !== undefined) el.textContent = String(value);
    return el;
  }
  const root = document.getElementById('root');
  const status = node('p');
  status.setAttribute('role', 'status');
  const content = node('section');
  const controls = node('fieldset');
  function action(text, run) {
    const button = node('button', text);
    button.onclick = () => Promise.resolve(run()).catch(error => { status.textContent = String(error); });
    return button;
  }
  const previous = action(label('Previous', '上一页'), () => load(page - 1));
  const next = action(label('Next', '下一页'), () => load(page + 1));
  const refresh = action(label('Refresh', '刷新'), () => load(page));
  let page = 1;
  controls.append(refresh);
  if (id) controls.append(action(title, () => window.memstack.navigate(base)));
  else controls.append(previous, next);
  root.append(node('h1', title), controls, status, content);
  const terms = {
    id: 'ID', name: label('Name','名称'), description: label('Description','说明'),
    status: label('Status','状态'), health_status: label('Health','健康状态'),
    cluster_id: label('Cluster ID','集群 ID'), runtime: label('Runtime','运行时'),
    image_version: label('Image version','镜像版本'), replicas: label('Replicas','目标副本'),
    available_replicas: label('Available replicas','可用副本'), current_revision: label('Revision','修订'),
    cpu_request: label('CPU request','CPU 请求'), cpu_limit: label('CPU limit','CPU 上限'),
    mem_request: label('Memory request','内存请求'), mem_limit: label('Memory limit','内存上限'),
    compute_provider: label('Compute provider','计算提供商'),
    last_health_check: label('Last health check','最近健康检查'), created_at: label('Created','创建时间'),
    updated_at: label('Updated','更新时间')
  };
  async function load(requestedPage) {
    controls.disabled = true;
    status.textContent = label('Loading…','正在加载…');
    try {
      const result = await window.memstack.invoke('environment-inventory', id ? { kind, id } : { kind, page:requestedPage });
      if (id) {
        const list = node('dl');
        for (const [key, name] of Object.entries(terms)) {
          if (result.item[key] != null) list.append(node('dt', name), node('dd', result.item[key]));
        }
        content.replaceChildren(node('h2', result.item.name), list);
      } else {
        const table = node('table');
        const head = table.createTHead().insertRow();
        for (const key of ['name','status','health_status']) head.append(node('th', terms[key]));
        const body = table.createTBody();
        for (const item of result.items) {
          const row = body.insertRow();
          row.insertCell().append(action(item.name, () => window.memstack.navigate(base + '/' + encodeURIComponent(item.id))));
          row.insertCell().textContent = item.status;
          row.insertCell().textContent = item.health_status ?? '—';
        }
        page = requestedPage;
        previous.disabled = page === 1;
        next.disabled = page * 20 >= result.total;
        content.replaceChildren(result.total ? table : node('p',label('No records in this tenant','此租户暂无记录')));
      }
      status.textContent = '';
    } finally { controls.disabled = false; }
  }
  try { await load(1); } catch (error) { status.textContent = String(error); }
})();

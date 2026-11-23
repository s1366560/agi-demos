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
  const form = node('form');
  const label = node('label', t('Search title or content', '搜索标题或正文'));
  const input = node('input');
  input.type = 'search';
  input.maxLength = 200;
  label.append(input);
  const submit = node('button', t('Search', '搜索'));
  submit.type = 'submit';
  form.append(label, submit);
  const list = node('ul');
  const more = node('button', t('Load more', '加载更多'));
  more.type = 'button';
  const status = node('p');
  status.setAttribute('role', 'status');
  root.append(node('h1', t('Project memories', '项目记忆')), form, list, more, status);

  let search = '';
  let offset = 0;
  let activeRequest = 0;
  async function load(reset) {
    const request = ++activeRequest;
    if (reset) {
      search = input.value.trim();
      offset = 0;
      list.replaceChildren();
    }
    more.hidden = true;
    status.textContent = t('Loading memories…', '正在加载记忆…');
    try {
      const page = await sdk.invoke('list-memories', {search, offset, limit: 20});
      if (request !== activeRequest) return;
      for (const item of page.items) {
        const row = node('li');
        row.append(node('h2', item.title), node('p', item.excerpt));
        list.append(row);
      }
      offset += page.items.length;
      more.hidden = !page.has_more;
      status.textContent = offset ? '' : t('No memories found.', '未找到记忆。');
    } catch (error) {
      if (request !== activeRequest) return;
      status.textContent = String(error);
      more.hidden = offset === 0;
    }
  }
  form.onsubmit = event => {
    event.preventDefault();
    void load(true);
  };
  more.onclick = () => load(false);
  await load(true);
})();

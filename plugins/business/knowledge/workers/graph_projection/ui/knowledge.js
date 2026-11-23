(async () => {
  const host = window.memstack;
  const context = await host.scope();
  const root = document.getElementById('root');
  const zh = navigator.language.startsWith('zh');
  const label = (en, cn) => zh ? cn : en;
  const title = document.createElement('h1');
  title.textContent = label('Knowledge', '知识库');
  root.append(title);
  function section(name, fields, submit) {
    const form = document.createElement('form');
    const heading = document.createElement('h2');
    heading.textContent = name;
    form.append(heading);
    const inputs = fields.map(([title, multiline]) => {
      const label = document.createElement('label');
      label.textContent = title;
      const field = document.createElement(multiline ? 'textarea' : 'input');
      field.required = true;
      label.append(field);
      form.append(label);
      return field;
    });
    const button = document.createElement('button');
    button.textContent = name;
    const output = document.createElement('pre');
    output.setAttribute('aria-live', 'polite');
    form.append(button, output);
    button.type = 'button';
    form.addEventListener('keydown', event => {
      if (event.key === 'Enter' && event.target instanceof HTMLInputElement) {
        event.preventDefault();
        button.click();
      }
    });
    button.onclick = async () => {
      if (!form.reportValidity()) return;
      button.disabled = true;
      try {
        output.textContent = JSON.stringify(await submit(...inputs.map(item => item.value)), null, 2);
      } catch (error) {
        output.textContent = String(error);
      } finally {
        button.disabled = false;
      }
    };
    root.append(form);
  }
  section(label('Project graph', '投影图谱'), [[label('Entity', '实体名称'), false], [label('Type', '类型'), false]],
    (name, kind) => host.invoke('project-graph', {nodes: [{uuid: '1', name, kind}], edges: []}));
  if (context.target === 'desktop-renderer') {
    section(label('Search on this device', '在本机检索'), [[label('Query', '查询'), false], [label('Document', '文档'), true]],
      (query, text) => host.device('search_documents', {query, documents: [{id: 'document', text}]}));
  }
})();

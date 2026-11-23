(() => {
  const root = document.getElementById('root');
  const zh = navigator.language.startsWith('zh');
  const label = (en, cn) => zh ? cn : en;
  const title = document.createElement('h1');
  title.textContent = label('Sandbox patch preview', '沙箱补丁预览');
  const form = document.createElement('form');
  function field(name) {
    const label = document.createElement('label');
    label.textContent = name;
    const input = document.createElement('textarea');
    input.required = true;
    input.rows = 8;
    label.append(input);
    form.append(label);
    return input;
  }
  const content = field(label('Original content', '原始内容'));
  const patch = field(label('Unified diff', '统一差异补丁'));
  const submit = document.createElement('button');
  submit.textContent = label('Apply to preview', '预览应用结果');
  const output = document.createElement('pre');
  output.setAttribute('aria-live', 'polite');
  submit.type = 'button';
  form.addEventListener('keydown', event => {
    if (event.key === 'Enter' && event.target instanceof HTMLInputElement) {
      event.preventDefault();
      submit.click();
    }
  });
  submit.onclick = async () => {
    if (!form.reportValidity()) return;
    submit.disabled = true;
    try {
      const result = await window.memstack.invoke('patch-text', {content: content.value, patch: patch.value});
      output.textContent = result.content;
    } catch (error) {
      output.textContent = String(error);
    } finally {
      submit.disabled = false;
    }
  };
  form.append(submit);
  root.append(title, form, output);
})();

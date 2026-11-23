(() => {
  const root = document.getElementById('root');
  const zh = navigator.language.startsWith('zh');
  const label = (en, cn) => zh ? cn : en;
  const title = document.createElement('h1');
  title.textContent = label('Agent skills', '智能体技能');
  const form = document.createElement('form');
  const editor = document.createElement('label');
  editor.textContent = 'SKILL.md';
  const content = document.createElement('textarea');
  content.rows = 16;
  content.required = true;
  editor.append(content);
  const submit = document.createElement('button');
  submit.textContent = label('Validate skill', '验证技能');
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
      const result = await window.memstack.invoke('validate-skill', {content: content.value});
      output.textContent = JSON.stringify(result, null, 2);
    } catch (error) {
      output.textContent = String(error);
    } finally {
      submit.disabled = false;
    }
  };
  form.append(editor, submit);
  root.append(title, form, output);
})();

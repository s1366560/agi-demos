(() => {
  const root = document.getElementById('root');
  const zh = navigator.language.startsWith('zh');
  const label = (en, cn) => zh ? cn : en;
  const title = document.createElement('h1');
  title.textContent = label('Schedule workflow', '调度工作流');
  const form = document.createElement('form');
  const steps = document.createElement('ol');
  const add = document.createElement('button');
  add.type = 'button';
  add.textContent = label('Add interval step', '添加间隔步骤');
  function addStep() {
    const step = document.createElement('li');
    const field = document.createElement('label');
    field.textContent = label('Interval in seconds', '间隔秒数');
    const seconds = document.createElement('input');
    Object.assign(seconds, {type: 'number', min: '1', max: '31536000', required: true, value: '60'});
    field.append(seconds);
    step.append(field);
    steps.append(step);
    add.disabled = steps.children.length >= 16;
  }
  add.onclick = addStep;
  addStep();
  const submit = document.createElement('button');
  submit.textContent = label('Run workflow', '执行工作流');
  const output = document.createElement('ol');
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
    output.replaceChildren();
    const start = new Date().toISOString();
    try {
      const result = await window.memstack.invoke('run-workflow', {
        steps: Array.from(steps.querySelectorAll('input'), field =>
          ({kind: 'every', config: {interval_seconds: field.valueAsNumber}, start})),
      });
      for (const step of result.results) {
        const item = document.createElement('li');
        item.textContent = step.next_run_at;
        output.append(item);
      }
    } catch (error) {
      output.textContent = String(error);
    } finally {
      submit.disabled = false;
    }
  };
  form.append(steps, add, submit);
  root.append(title, form, output);
})();

(async () => {
  const api = window.memstack;
  const {locale} = await api.scope();
  const zh = locale.startsWith('zh');
  const root = document.getElementById('root');
  const title = document.createElement('h1');
  title.textContent = zh ? '项目剧本' : 'Project playbooks';
  const refresh = document.createElement('button');
  refresh.textContent = zh ? '刷新' : 'Refresh';
  const results = document.createElement('section');
  results.setAttribute('aria-live', 'polite');
  async function load() {
    refresh.disabled = true;
    try {
      const {items} = await api.invoke('list-playbooks');
      results.replaceChildren();
      for (const item of items) {
        const details = document.createElement('details');
        const name = document.createElement('summary');
        name.textContent = item.name;
        const trigger = document.createElement('p');
        trigger.textContent = item.trigger.description;
        const steps = document.createElement('ol');
        for (const step of item.steps) {
          const entry = document.createElement('li');
          entry.textContent = step.instruction;
          steps.append(entry);
        }
        details.append(name, trigger, steps);
        results.append(details);
      }
      if (!items.length) results.textContent = zh ? '暂无剧本' : 'No project playbooks';
    } catch (error) {
      results.textContent = String(error);
    } finally {
      refresh.disabled = false;
    }
  }
  refresh.onclick = load;
  root.append(title, refresh, results);
  await load();
})();

(async () => {
  const api = window.memstack;
  const {locale, commands, pathname, search, hash} = await api.scope();
  const label = (en, zh) => locale.startsWith('zh') ? zh : en;
  const node = (tag, text) => Object.assign(document.createElement(tag), text === undefined ? {} : {textContent:text});
  const root = document.getElementById('root');
  const title = node('h1', label('Schedule workflow', '调度工作流'));
  const editor = node('fieldset');
  function field(parent, text, element) {
    const caption = node('label', text);
    caption.append(element);
    parent.append(caption);
    return element;
  }
  const choice = field(editor, label('Saved revisions','已保存版本'),node('select'));
  const name = field(editor, label('Workflow name','工作流名称'),Object.assign(node('input'),{maxLength:160,required:true}));
  const steps = node('ol');
  editor.append(steps);
  const notice = node('p');
  notice.setAttribute('role','status');
  const output = node('ol');
  output.setAttribute('aria-live','polite');
  function button(text, callback) {
    const action = node('button',text);
    action.type = 'button';
    action.onclick = async () => {
      editor.disabled = true;
      notice.textContent = '';
      try { await callback(); } catch (error) { notice.textContent = String(error); }
      finally { editor.disabled = false; }
    };
    editor.append(action);
    return action;
  }
  let selected = null, newId = '', cursor = null;
  const revisions = new Map();
  const link = new URLSearchParams(search);
  const workflow = link.get('workflow');
  const revision = link.get('revision');
  const bookmark = workflow && revision ? workflow + ':' + revision : null;
  async function updateBookmark() {
    const query = new URLSearchParams();
    if (selected) {
      query.set('workflow', selected.id);
      query.set('revision', String(selected.revision));
    }
    await api.navigate(pathname + (query.size ? '?' + query : '') + (hash || ''), {replace:true});
  }
  function values() { return Array.from(steps.querySelectorAll('input'), input => input.valueAsNumber); }
  function changed() {
    add.disabled = steps.children.length >= 16;
    runSaved.disabled = !selected || selected.name !== name.value || JSON.stringify(selected.intervals) !== JSON.stringify(values());
    for (const remove of steps.querySelectorAll('button')) remove.disabled = steps.children.length <= 1;
  }
  function addStep(interval = 60) {
    const step = node('li');
    const control = Object.assign(node('input'),{type:'number',min:'1',max:'31536000',value:String(interval),required:true});
    field(step,label('Interval in seconds','间隔秒数'),control);
    control.oninput = changed;
    const remove = node('button',label('Remove step','移除步骤'));
    remove.type = 'button';
    remove.onclick = () => {step.remove();changed();};
    step.append(remove);
    steps.append(step);
  }
  function select() {
    selected = revisions.get(choice.value) ?? null;
    newId = Array.from(crypto.getRandomValues(new Uint32Array(4)), x=>x.toString(16).padStart(8,'0')).join('');
    name.value = selected?.name ?? '';
    steps.replaceChildren();
    for (const interval of selected?.intervals ?? [60]) addStep(interval);
    output.replaceChildren();
    notice.textContent = '';
    changed();
  }
  function show(record) {
    const key = record.id + ':' + record.revision;
    if (!revisions.has(key)) choice.add(new Option(record.name + ' · v' + record.revision,key));
    revisions.set(key,record);
    return key;
  }
  async function load(reset) {
    const page = await api.invoke('list-workflows', reset || !cursor ? {} : {after:cursor});
    if (reset) {
      revisions.clear();
      choice.replaceChildren(new Option(label('New workflow','新建工作流'),''));
      select();
    }
    for (const item of page.items) show(item);
    cursor = page.next_cursor;
    more.disabled = !cursor;
  }
  const more = button(label('Load more revisions','载入更多版本'), () => load(false));
  const add = button(label('Add interval step','添加间隔步骤'), () => {addStep();changed();});
  const save = button(label('Save workflow','保存工作流'), async () => {
    if (!name.reportValidity() || !Array.from(steps.querySelectorAll('input')).every(input => input.reportValidity())) return;
    const draft = {id:selected?.id ?? newId, name:name.value, intervals:values()};
    const result = await api.invoke('save-workflow',{...draft, expected_revision:selected?.revision ?? 0});
    if (!result.saved) throw new Error(label('A newer revision exists. Reload saved revisions.','已有更新版本，请重新载入。'));
    choice.value = show({...draft,revision:result.revision});
    select();
    await updateBookmark();
    notice.textContent = label('Saved revision ','已保存版本 ') + result.revision;
  });
  function render(result) {
    output.replaceChildren(...result.results.map(step => node('li', step.next_run_at ?? label('No scheduled time','无计划时间'))));
  }
  button(label('Run workflow','执行工作流'), async () => {
    if (!Array.from(steps.querySelectorAll('input')).every(input => input.reportValidity())) return;
    const start = new Date().toISOString();
    render(await api.invoke('run-workflow',{steps:values().map(interval=>({kind:'every',config:{interval_seconds:interval},start}))}));
  });
  const runSaved = button(label('Run saved revision','运行已保存版本'), async () => {
    if (selected) render(await api.invoke('execute-workflow',{id:selected.id,revision:selected.revision,start:new Date().toISOString()}));
  });
  button(label('Reload saved revisions','重新载入版本'), () => load(true));
  save.disabled = !commands.includes('save-workflow');
  choice.onchange = async () => { select(); await updateBookmark(); };
  name.oninput = changed;
  root.append(title,editor,notice,output);
  select();
  editor.disabled = true;
  try {
    await load(true);
    if (bookmark) {
      while (cursor && !revisions.has(bookmark)) await load(false);
      if (revisions.has(bookmark)) {
        choice.value = bookmark;
        select();
      } else {
        notice.textContent = label('Workflow revision unavailable', '工作流版本不可用');
      }
    }
  } catch (error) { notice.textContent=String(error); }
  finally { editor.disabled = false; }
})();

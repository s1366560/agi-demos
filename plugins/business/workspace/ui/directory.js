(async () => {
  const root = document.getElementById('root');
  const scope = await window.memstack.getContext();
  const zh = scope.locale.startsWith('zh');
  const label = (en, cn) => zh ? cn : en;
  const title = document.createElement('h1');
  title.textContent = label('Workspace directory', '工作区目录');
  const project = document.createElement('p');
  project.textContent = label('Project ', '项目 ') + scope.projectId;
  const form = document.createElement('form');
  const rows = document.createElement('tbody');
  const table = document.createElement('table');
  const head = table.createTHead().insertRow();
  const columns = ['ID', label('Name', '名称'), label('Status', '状态'), label('Archived', '已归档')];
  for (const name of columns) {
    const cell = document.createElement('th');
    cell.textContent = name;
    head.append(cell);
  }
  table.append(rows);
  const add = document.createElement('button');
  add.type = 'button';
  add.textContent = label('Add row', '添加记录');
  function addRow(workspace) {
    const row = rows.insertRow();
    columns.forEach((column, index) => {
      const input = document.createElement('input');
      input.type = index === 3 ? 'checkbox' : 'text';
      input.setAttribute('aria-label', column);
      if (workspace) {
        if (index === 3) input.checked = workspace.is_archived;
        else input.value = [workspace.id, workspace.name, workspace.office_status][index];
      }
      input.required = index < 2;
      input.maxLength = [128, 255, 128][index] || 128;
      row.insertCell().append(input);
    });
    add.disabled = rows.rows.length === 8;
  }
  add.onclick = () => addRow();
  addRow();
  const submit = document.createElement('button');
  submit.textContent = label('Export CSV', '导出 CSV');
  const output = document.createElement('pre');
  output.setAttribute('aria-live', 'polite');
  submit.type = 'button';
  form.addEventListener('keydown', event => {
    if (event.key === 'Enter' && event.target instanceof HTMLInputElement) {
      event.preventDefault();
      submit.click();
    }
  });
  const save = document.createElement('button');
  save.type = 'button';
  save.hidden = true;
  save.textContent = label('Save CSV file', '保存 CSV 文件');
  let exportedRows;
  save.onclick = async () => {
    if (!exportedRows) return;
    save.disabled = true;
    try {
      await window.memstack.exportCsv('export-csv', {header: true, rows: exportedRows});
    } catch (error) {
      output.textContent = String(error);
    } finally {
      save.disabled = false;
    }
  };
  form.addEventListener('input', () => { save.hidden = true; });
  submit.onclick = async () => {
    save.hidden = true;
    if (!form.reportValidity()) return;
    submit.disabled = true;
    try {
      const records = Array.from(rows.rows, row => {
        const [id, name, status, archived] = row.querySelectorAll('input');
        return { id: id.value, name: name.value, office_status: status.value, is_archived: archived.checked };
      });
      const result = await window.memstack.invoke('export-csv', {header: true, rows: records});
      output.textContent = result.csv;
      exportedRows = records;
      save.hidden = typeof window.memstack.exportCsv !== 'function';
    } catch (error) {
      output.textContent = String(error);
    } finally {
      submit.disabled = false;
    }
  };
  const browse = document.createElement('button');
  browse.type = 'button';
  browse.textContent = label('Load project directory', '读取项目目录');
  browse.onclick = async () => {
    browse.disabled = true;
    try {
      const result = await window.memstack.invoke('list-directory', {limit: 8});
      rows.replaceChildren();
      add.disabled = false;
      result.rows.forEach(addRow);
      output.textContent = result.rows.length ? '' : label('No workspaces in this project', '当前项目暂无工作区');
    } catch (error) {
      output.textContent = String(error);
    } finally {
      browse.disabled = false;
    }
  };
  const editor = document.createElement('div');
  editor.className = 'directory-rows';
  editor.tabIndex = 0;
  editor.setAttribute('role', 'region');
  editor.setAttribute('aria-label', label('Workspace rows', '工作区记录'));
  editor.append(table);
  form.append(browse, editor, add, submit);
  const directory = '/tenant/' + encodeURIComponent(scope.tenantId) + '/project/' + encodeURIComponent(scope.projectId) + '/workspaces';
  const status = document.createElement('p');
  status.setAttribute('role', 'status');
  const link = (title, path) => {
    const anchor = document.createElement('a');
    anchor.textContent = title;
    anchor.href = path;
    anchor.onclick = event => {
      event.preventDefault();
      window.memstack.navigate(path).catch(error => { status.textContent = error.message; });
    };
    return anchor;
  };
  root.append(link(label('Workspace directory', '工作区目录'), directory),
    Object.assign(document.createElement('h1'), { textContent: label('CSV export', '导出 CSV') }),
    project, form, output, save, status);
})();

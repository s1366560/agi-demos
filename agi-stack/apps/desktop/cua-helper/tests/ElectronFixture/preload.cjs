const { ipcRenderer } = require('electron');

window.addEventListener('DOMContentLoaded', () => {
  const input = document.querySelector('input');
  const index = new URLSearchParams(location.search).get('index');
  input.value = `Fixture ${index} text`;
  const keyCodes = { ShiftLeft: 56, ShiftRight: 60, KeyA: 0, KeyB: 11 };
  let dragStart = null;
  let dragMoved = false;
  for (const name of ['keydown', 'keyup', 'mousedown', 'mouseup', 'mousemove', 'wheel', 'click']) {
    window.addEventListener(name, (event) => {
      if (name === 'mousedown' && event.target.id === 'canvas') {
        dragStart = [event.clientX, event.clientY]; dragMoved = false;
      }
      if (name === 'mousemove' && dragStart && (event.buttons & 1)) dragMoved = true;
      if (name === 'mouseup' && dragStart) {
        if (dragMoved) document.querySelector('#drag-status').textContent =
          `drag complete:${event.clientX - dragStart[0]},${event.clientY - dragStart[1]}`;
        dragStart = null;
      }
      const flags = (event.shiftKey ? 131072 : 0) | (event.ctrlKey ? 262144 : 0)
        | (event.altKey ? 524288 : 0) | (event.metaKey ? 1048576 : 0);
      let type;
      if (name === 'keydown' || name === 'keyup') {
        type = event.key === 'Shift' ? 12 : name === 'keydown' ? 10 : 11;
        document.querySelector('#shift').textContent = `Shift held: ${event.shiftKey}`;
      } else if (name === 'mousedown' || name === 'mouseup') {
        type = (name === 'mousedown' ? [1, 25, 3] : [2, 26, 4])[event.button];
        document.querySelector('#mouse').textContent = `Left button held: ${Boolean(event.buttons & 1)}`;
      } else if (name === 'wheel') type = 22;
      else if (name === 'click') type = 999;
      else type = event.buttons & 1 ? 6 : 5;
      ipcRenderer.send('fixture-input', {
        type, flags, key_code: keyCodes[event.code], characters: event.key || '',
        x: event.clientX || 0, y: event.clientY || 0, trusted: event.isTrusted,
        click_count: event.detail || 0,
        dom_type: name,
        buttons: event.buttons || 0,
      });
    }, true);
  }
  window.addEventListener('contextmenu', (event) => event.preventDefault());
});

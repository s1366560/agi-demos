const { app, BrowserWindow, ipcMain, screen } = require('electron');
const { appendFileSync, writeFileSync } = require('node:fs');
const path = require('node:path');

app.setPath('userData', process.env.CUA_FIXTURE_ELECTRON_DATA);
app.setName('Background Electron Fixture');
app.commandLine.appendSwitch('force-renderer-accessibility');
const windows = [];
ipcMain.on('fixture-input', (event, value) => {
  const window = BrowserWindow.fromWebContents(event.sender);
  if (!window || !windows.includes(window)) return;
  appendFileSync(process.env.CUA_FIXTURE_JSON_LOG, JSON.stringify({ ...value, window: window.id }) + '\n');
});
app.whenReady().then(async () => {
  const display = screen.getPrimaryDisplay().bounds;
  for (let index = 1; index <= 2; index += 1) {
    const window = new BrowserWindow({
      x: display.x + 160 + index * 40,
      y: display.y + display.height - 592 - index * 40,
      width: 560,
      height: 432,
      title: `Background Target ${index}`,
      show: false,
      webPreferences: {
        preload: path.join(__dirname, 'preload.cjs'),
        contextIsolation: true,
        sandbox: true,
        backgroundThrottling: false,
      },
    });
    windows.push(window);
    await window.loadFile(path.join(__dirname, 'page.html'), { query: { index: String(index) } });
    window.setTitle(`Background Target ${index}`);
    window.showInactive();
  }
});
app.on('window-all-closed', () => app.quit());
process.on('SIGTERM', () => app.quit());
process.on('SIGUSR2', () => {
  for (const window of windows) {
    const [x, y] = window.getPosition();
    window.setPosition(x + 650, y + 25);
  }
  writeFileSync(process.env.CUA_FIXTURE_MOVE_ACK, 'moved\n');
});

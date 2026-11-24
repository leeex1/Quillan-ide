const { app, BrowserWindow, ipcMain, dialog, Menu, shell } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

let serverProcess = null;
let mainWindow = null;
const defaultWorkspace = 'C:\\02_QUILLAN';
let workspace = process.env.QUILLANCODE_WORKSPACE ||
  (fs.existsSync(defaultWorkspace) ? defaultWorkspace : process.cwd());

function startServer(port) {
  serverProcess = spawn('quillancode', [
    '--cwd', workspace, 'serve', '--host', '127.0.0.1', '--port', String(port),
  ], { cwd: workspace, env: process.env, stdio: ['ignore', 'pipe', 'pipe'] });
  serverProcess.stderr.on('data', (d) => process.stderr.write(d));
}

function send(channel) {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send(channel);
}

async function chooseFolder() {
  const result = await dialog.showOpenDialog({ properties: ['openDirectory'] });
  if (result.canceled || !result.filePaths.length) return { canceled: true };
  workspace = result.filePaths[0];
  if (serverProcess) serverProcess.kill();
  startServer(Number(process.env.QUILLANCODE_PORT || 4096));
  send('workspace-changed');
  return { canceled: false, path: workspace };
}

ipcMain.handle('open-folder', chooseFolder);

function buildMenu() {
  const template = [
    {
      label: 'File',
      submenu: [
        { label: 'Open Folder…', accelerator: 'CmdOrCtrl+O', click: () => chooseFolder() },
        { label: 'New Window', accelerator: 'CmdOrCtrl+N', click: () => createWindow() },
        { type: 'separator' },
        { label: 'Save Active File', accelerator: 'CmdOrCtrl+S', click: () => send('menu-save') },
        { label: 'Quick Open…', accelerator: 'CmdOrCtrl+P', click: () => send('menu-quick-open') },
        { type: 'separator' },
        { label: 'Exit', accelerator: 'CmdOrCtrl+Q', click: () => app.quit() },
      ],
    },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' }, { role: 'redo' }, { type: 'separator' },
        { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' },
      ],
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' }, { role: 'forceReload' },
        { type: 'separator' }, { role: 'toggleDevTools' },
        { type: 'separator' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { role: 'resetZoom' },
      ],
    },
    {
      label: 'Agent',
      submenu: [
        { label: 'Focus Prompt', accelerator: 'CmdOrCtrl+L', click: () => send('menu-focus-prompt') },
        { label: 'Clear Conversation', click: () => send('menu-clear-chat') },
        { label: 'Review Current File', click: () => send('menu-review') },
      ],
    },
    {
      label: 'Help',
      submenu: [
        { label: 'quillancode README', click: () => shell.openExternal(
            'https://github.com/leeex1/Quillan-ide') },
        { label: 'About', click: () => dialog.showMessageBox({
            type: 'info', title: 'quillancode',
            message: 'quillancode — sovereign multi-provider agentic IDE',
            detail: 'C0 Throne · 34-seat council · BYO providers · local tensor/checkpoint inspection',
          }) },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function createWindow() {
  const port = Number(process.env.QUILLANCODE_PORT || 4096);
  if (!serverProcess) startServer(port);
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    icon: path.join(__dirname, 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  setTimeout(() => mainWindow.loadURL(`http://127.0.0.1:${port}/ide`), 500);
  mainWindow.on('closed', () => { mainWindow = null; });
}

app.whenReady().then(() => { buildMenu(); createWindow(); });
app.on('window-all-closed', () => {
  if (serverProcess) serverProcess.kill();
  if (process.platform !== 'darwin') app.quit();
});
app.on('activate', () => { if (!mainWindow) createWindow(); });

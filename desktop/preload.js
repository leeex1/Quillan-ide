const { contextBridge, ipcRenderer } = require('electron');

const on = (channel, handler) => ipcRenderer.on(channel, (_event, ...args) => handler(...args));

contextBridge.exposeInMainWorld('quillancode', {
  openFolder: () => ipcRenderer.invoke('open-folder'),
  copyText: (text) => ipcRenderer.invoke('clipboard-write', text),
  readClipboard: () => ipcRenderer.invoke('clipboard-read'),
  onSave: (fn) => on('menu-save', fn),
  onQuickOpen: (fn) => on('menu-quick-open', fn),
  onFocusPrompt: (fn) => on('menu-focus-prompt', fn),
  onClearChat: (fn) => on('menu-clear-chat', fn),
  onReview: (fn) => on('menu-review', fn),
  onWorkspaceChanged: (fn) => on('workspace-changed', fn),
  onCopyFile: (fn) => on('menu-copy-file', fn),
});

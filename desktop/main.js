// Orbit desktop shell. It opens the Orbit web UI that runs on your VM.
const { app, BrowserWindow, Menu, shell } = require("electron");
const fs = require("fs");
const path = require("path");

const settingsFile = () => path.join(app.getPath("userData"), "settings.json");
const readSettings = () => { try { return JSON.parse(fs.readFileSync(settingsFile(), "utf8")); } catch { return {}; } };
const writeSettings = (s) => fs.writeFileSync(settingsFile(), JSON.stringify(s, null, 2));

let win;

function openServer(url) {
  win.loadURL(url).catch(() => win.loadFile("setup.html", { query: { error: `Cannot reach ${url}. Is Tailscale on?` } }));
}

function createWindow() {
  win = new BrowserWindow({
    width: 1400, height: 900, title: "Orbit", backgroundColor: "#0b0d12",
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  // Links that leave the app open in your normal browser.
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: "deny" }; });
  const { serverUrl } = readSettings();
  if (serverUrl) openServer(serverUrl);
  else win.loadFile("setup.html");
}

// setup.html navigates to orbit-setup://save?url=... to store the server URL.
app.whenReady().then(() => {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: "Orbit", submenu: [
      { label: "Change server…", click: () => win.loadFile("setup.html") },
      { role: "reload" }, { role: "toggleDevTools" }, { type: "separator" }, { role: "quit" },
    ] },
    { role: "editMenu" },
  ]));
  createWindow();
  win.webContents.on("will-navigate", (e, url) => {
    if (url.startsWith("orbit-setup://")) {
      e.preventDefault();
      const serverUrl = new URL(url).searchParams.get("url");
      writeSettings({ ...readSettings(), serverUrl });
      openServer(serverUrl);
    }
  });
});

app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });

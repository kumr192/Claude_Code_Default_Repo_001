// Orbit desktop shell. It opens the Orbit web UI that runs on your VM.
const { app, BrowserWindow, Menu, shell } = require("electron");
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");

const settingsFile = () => path.join(app.getPath("userData"), "settings.json");
const readSettings = () => { try { return JSON.parse(fs.readFileSync(settingsFile(), "utf8")); } catch { return {}; } };
const writeSettings = (s) => fs.writeFileSync(settingsFile(), JSON.stringify(s, null, 2));

let win;
let keepAlive = null;

// Free local mode: Orbit runs inside WSL on this PC. Keep WSL running while
// the app is open (WSL stops a distro when nothing uses it).
function startWsl() {
  const { serverUrl, wslDistro = "Ubuntu-24.04" } = readSettings();
  if (process.platform !== "win32" || !serverUrl || !serverUrl.includes("localhost")) return;
  keepAlive = spawn("wsl.exe", ["-d", wslDistro, "--exec", "sleep", "infinity"], { windowsHide: true, stdio: "ignore" });
  keepAlive.on("error", () => { keepAlive = null; });
}

// Try for up to ~40 s, because WSL and the server need time to start.
async function openServer(url, tries = 20) {
  for (let i = 0; i < tries; i++) {
    try { await win.loadURL(url); return; } catch { await new Promise((r) => setTimeout(r, 2000)); }
  }
  win.loadFile("setup.html", { query: { error: `Cannot reach ${url}. Is Orbit running? (local: open Ubuntu once; cloud: is Tailscale on?)` } });
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
  startWsl();
  createWindow();
  win.webContents.on("will-navigate", (e, url) => {
    if (url.startsWith("orbit-setup://")) {
      e.preventDefault();
      const serverUrl = new URL(url).searchParams.get("url");
      writeSettings({ ...readSettings(), serverUrl });
      if (!keepAlive) startWsl();
      openServer(serverUrl);
    }
  });
});

app.on("quit", () => { if (keepAlive) keepAlive.kill(); });
app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });

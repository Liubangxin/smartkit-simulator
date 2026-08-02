const { app, BrowserWindow, dialog } = require("electron");
const { spawn, execFileSync } = require("child_process");
const path = require("path");
const fs = require("fs");
const readline = require("readline");

const READY_TIMEOUT_MS = 30000;

let backendProcess = null;
let mainWindow = null;
let readyPort = null;
let isQuitting = false;

function projectRoot() {
  return path.resolve(__dirname, "..");
}

function resolveBackendCommand() {
  const root = projectRoot();
  if (app.isPackaged) {
    return {
      command: path.join(process.resourcesPath, "backend", "simulator_gui.exe"),
      args: [],
    };
  }
  const venvPython = path.join(root, ".venv", "Scripts", "python.exe");
  const python = fs.existsSync(venvPython) ? venvPython : "python";
  return { command: python, args: [path.join(root, "simulator_gui.py")] };
}

function resolveDataDir() {
  // Portable exe: store data next to the exe
  if (process.env.PORTABLE_EXECUTABLE_DIR) {
    return process.env.PORTABLE_EXECUTABLE_DIR;
  }
  if (app.isPackaged) {
    return app.getPath("userData");
  }
  return projectRoot();
}

function killBackendTree() {
  if (!backendProcess || !backendProcess.pid) return;
  try {
    execFileSync("taskkill", ["/pid", String(backendProcess.pid), "/T", "/F"], {
      stdio: "ignore",
    });
  } catch (_) {
    try { backendProcess.kill(); } catch (_) {}
  }
  backendProcess = null;
}

function showFatal(message) {
  dialog.showErrorBox("SmartKit Simulator", message);
  isQuitting = true;
  app.exit(1);
}

function startBackend() {
  return new Promise((resolve, reject) => {
    const { command, args } = resolveBackendCommand();
    const fullArgs = [...args, "--headless", "--data-dir", resolveDataDir()];

    backendProcess = spawn(command, fullArgs, {
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stderr = "";
    backendProcess.stderr.on("data", (d) => { stderr += d.toString(); });

    backendProcess.on("error", (err) => {
      reject(new Error(`Failed to start backend: ${err.message}\n${stderr}`));
    });

    const timer = setTimeout(() => {
      reject(
        new Error(
          `Backend startup timed out after ${READY_TIMEOUT_MS / 1000}s\n${stderr}`
        )
      );
    }, READY_TIMEOUT_MS);

    const rl = readline.createInterface({ input: backendProcess.stdout });
    rl.on("line", (line) => {
      const m = line.match(/^SMARTKIT_READY_PORT=(\d+)$/);
      if (m) {
        clearTimeout(timer);
        rl.close();
        resolve(parseInt(m[1], 10));
      }
    });
  });
}

app.whenReady().then(async () => {
  try {
    readyPort = await startBackend();
  } catch (err) {
    showFatal(err.message);
    return;
  }

  // Only show fatal if backend exits unexpectedly (not during app quit)
  backendProcess.on("exit", (code) => {
    if (!isQuitting && code !== 0) {
      showFatal(`Backend exited unexpectedly (code ${code}).`);
    }
  });

  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.on("closed", () => { mainWindow = null; });
  mainWindow.loadURL(`http://127.0.0.1:${readyPort}`);
});

app.on("window-all-closed", () => {
  isQuitting = true;
  killBackendTree();
  app.quit();
});

app.on("before-quit", () => {
  isQuitting = true;
});

app.on("will-quit", killBackendTree);

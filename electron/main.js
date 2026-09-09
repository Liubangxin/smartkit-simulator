const { app, BrowserWindow, dialog, ipcMain, screen } = require("electron");
const { spawn, execFileSync } = require("child_process");
const path = require("path");
const fs = require("fs");
const readline = require("readline");

const READY_TIMEOUT_MS = 30000;
const DEFAULT_MANAGEMENT_PORT = 35800;
const AUTOMATION_MODE = process.argv.includes("--automation");

let backendProcess = null;
let mainWindow = null;
let readyPort = null;
let isQuitting = false;
let quitConfirmed = false;
let quitDialogOpen = false;

function projectRoot() {
  return path.resolve(__dirname, "..");
}

function commandLineValue(name) {
  const prefix = `${name}=`;
  const inline = process.argv.find((value) => value.startsWith(prefix));
  if (inline) return inline.slice(prefix.length);
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : undefined;
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
  const configured = commandLineValue("--data-dir");
  if (configured) {
    return path.resolve(configured);
  }
  // Portable exe: store data next to the exe
  if (process.env.PORTABLE_EXECUTABLE_DIR) {
    return process.env.PORTABLE_EXECUTABLE_DIR;
  }
  if (app.isPackaged) {
    return app.getPath("userData");
  }
  return projectRoot();
}

function resolveManagementPort() {
  const configured = commandLineValue("--management-port");
  if (configured === undefined) return DEFAULT_MANAGEMENT_PORT;
  const port = Number(configured);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("--management-port must be an integer between 1 and 65535");
  }
  return port;
}

function resolveAttachedManagementUrl() {
  const configured = commandLineValue("--attach-management-url");
  if (configured === undefined) return null;
  let target;
  try {
    target = new URL(configured);
  } catch (_) {
    throw new Error("--attach-management-url must be a valid URL");
  }
  if (target.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(target.hostname)) {
    throw new Error("--attach-management-url must use localhost HTTP");
  }
  if (!target.port || (target.pathname !== "/" && target.pathname !== "")) {
    throw new Error("--attach-management-url must contain only a host and explicit port");
  }
  return target.origin;
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

// Only the management page hosted by our own local backend may ask for a
// folder picker; anything else (redirects, devtools navigation) is ignored.
function isTrustedDialogSender(event) {
  if (!mainWindow || !event.sender || event.sender !== mainWindow.webContents) return false;
  let url;
  try {
    url = event.senderFrame ? new URL(event.senderFrame.url) : new URL(event.sender.getURL());
  } catch (_) {
    return false;
  }
  return (
    (url.protocol === "http:" || url.protocol === "https:") &&
    (url.hostname === "127.0.0.1" || url.hostname === "localhost")
  );
}

// Native "choose a folder" dialog for the dataset-directory pickers in the
// workbench page. Resolves with the picked absolute path, or null on cancel.
ipcMain.handle("pick-directory", async (event, defaultPath) => {
  if (!isTrustedDialogSender(event)) return null;
  const options = {
    title: "选择数据集目录",
    buttonLabel: "选择此文件夹",
    properties: ["openDirectory", "createDirectory"],
  };
  if (typeof defaultPath === "string" && defaultPath.trim()) {
    options.defaultPath = defaultPath.trim();
  }
  const result = await dialog.showOpenDialog(mainWindow, options);
  return result && !result.canceled && result.filePaths.length
    ? result.filePaths[0]
    : null;
});

function confirmAndQuit() {
  if (AUTOMATION_MODE || quitConfirmed || quitDialogOpen || !mainWindow) return;
  quitDialogOpen = true;
  dialog
    .showMessageBox(mainWindow, {
      type: "question",
      buttons: ["退出", "取消"],
      defaultId: 1,
      cancelId: 1,
      noLink: true,
      title: "退出 SmartKit Simulator",
      message: "确定要关闭 SmartKit 模拟器吗？",
      detail: "关闭后 SSH / REST 模拟服务将停止，正在运行的测试会话将被中断。",
    })
    .then(({ response }) => {
      if (response === 0) {
        quitConfirmed = true;
        isQuitting = true;
        app.quit();
      }
    })
    .catch(() => {})
    .finally(() => {
      quitDialogOpen = false;
    });
}

function showFatal(message) {
  if (AUTOMATION_MODE) {
    console.error(message);
    isQuitting = true;
    app.exit(1);
    return;
  }
  dialog.showErrorBox("SmartKit Simulator", message);
  isQuitting = true;
  app.exit(1);
}

function startBackend() {
  return new Promise((resolve, reject) => {
    const { command, args } = resolveBackendCommand();
    const fullArgs = [...args, "--headless", "--data-dir", resolveDataDir()];
    const managementPort = resolveManagementPort();
    if (managementPort !== null) {
      fullArgs.push("--management-port", String(managementPort));
    }

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
  let targetUrl;
  try {
    const attachedManagementUrl = resolveAttachedManagementUrl();
    if (attachedManagementUrl && AUTOMATION_MODE) {
      throw new Error("--automation cannot be combined with --attach-management-url");
    }
    if (attachedManagementUrl) {
      targetUrl = attachedManagementUrl;
    } else {
      readyPort = await startBackend();
      targetUrl = `http://127.0.0.1:${readyPort}`;
    }
  } catch (err) {
    showFatal(err.message);
    return;
  }

  // Only show fatal if backend exits unexpectedly (not during app quit)
  if (backendProcess) {
    backendProcess.on("exit", (code) => {
      if (!isQuitting && code !== 0) {
        showFatal(`Backend exited unexpectedly (code ${code}).`);
      }
    });
  }

  if (AUTOMATION_MODE) {
    return;
  }

  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    show: true,
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, "preload.js"),
    },
  });

  const workArea = screen.getPrimaryDisplay().workArea;
  const windowWidth = Math.min(1280, workArea.width);
  const windowHeight = Math.min(800, workArea.height);
  mainWindow.setBounds({
    x: workArea.x + Math.max(0, Math.round((workArea.width - windowWidth) / 2)),
    y: workArea.y + Math.max(0, Math.round((workArea.height - windowHeight) / 2)),
    width: windowWidth,
    height: windowHeight,
  });
  mainWindow.show();
  mainWindow.focus();
  mainWindow.on("closed", () => { mainWindow = null; });
  mainWindow.on("close", (event) => {
    if (quitConfirmed) return;
    event.preventDefault();
    confirmAndQuit();
  });
  mainWindow.loadURL(targetUrl);
});

app.on("window-all-closed", () => {
  isQuitting = true;
  killBackendTree();
  app.quit();
});

app.on("before-quit", (event) => {
  if (AUTOMATION_MODE || quitConfirmed) {
    isQuitting = true;
    return;
  }
  event.preventDefault();
  confirmAndQuit();
});

app.on("will-quit", killBackendTree);

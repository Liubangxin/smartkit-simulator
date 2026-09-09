// Preload: exposes a minimal opt-in desktop bridge to the simulator workbench
// page. The window runs sandboxed (contextIsolation + sandbox:true), so only
// the capabilities listed here are reachable from the renderer.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("smartkitDesktop", {
  // Opens a native "choose a folder" dialog in the main process. Resolves with
  // the picked absolute path, or null when the user cancels. `defaultPath` is
  // best-effort and only used as the dialog's starting location.
  pickDirectory: (defaultPath) =>
    ipcRenderer.invoke("pick-directory", defaultPath || ""),
});

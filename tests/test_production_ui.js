const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync("prototype_dataset_ui_a_full.html", "utf8");
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];

assert.doesNotThrow(() => new Function(script));
assert.ok(html.includes("数据集工作台"));
assert.ok(html.includes("模拟器运行"));
assert.ok(html.includes("/api/datasets?page="));
assert.ok(html.includes("/api/bindings?dataset_id="));
assert.ok(html.includes("/api/runtime/activate-dataset"));
assert.ok(html.includes("/api/dataset-directory/switch"));
assert.ok(!html.includes("THROWAWAY PROTOTYPE"));
assert.ok(!html.includes("所有操作仅在内存中"));
assert.ok(!html.includes("for(let i=1;i<=1283"));
assert.match(html, /#root\s*\{[^}]*height\s*:\s*100%/s,
  "the dynamic UI root must fill the viewport so flex children do not leave bottom whitespace");
assert.match(html, /\.runtime-overview\s*\{[^}]*flex\s*:\s*1/s,
  "runtime overview must consume the remaining vertical space above the log panel");
assert.match(html, /\.runtime-overview\s*\{[^}]*min-height\s*:\s*0/s,
  "runtime overview must be allowed to shrink inside the application flex column");
assert.ok(html.includes("新增分组"), "SSH/REST editors must expose group creation");
assert.ok(html.includes("renameGroup"), "groups must support rename");
assert.ok(html.includes("deleteGroup"), "groups must support deletion");
assert.ok(html.includes("/api/rest/import-log/preview"),
  "the production REST editor must call the log import preview API");
assert.ok(html.includes("根据日志导入"), "the REST editor must expose log import");
assert.ok(html.includes("/api/ssh/import-log/preview"),
  "the production SSH editor must call the SSH log import preview API");
assert.ok(html.includes("openSshLogImport"),
  "the SSH editor must expose log import beside its command actions");
assert.ok(html.includes("ssh-command-choice"),
  "SSH log preview must allow selecting only importable commands");
assert.ok(html.includes("confirmSshLogImport"),
  "selected SSH log commands must be persisted to the current dataset");
assert.ok(html.includes("panel-actions-stack"),
  "item and group actions must be split into a dedicated stacked toolbar");
assert.ok(html.includes("action-row item-actions"),
  "item actions must have their own visible row");
assert.ok(html.includes("action-row group-actions"),
  "group actions must have their own visible row");
assert.match(html, /\.panel-actions-stack\s*\{[^}]*flex\s*:\s*none/s,
  "the stacked toolbar must not be clipped by list flex sizing");
assert.ok(html.includes("layout-resizer vertical"),
  "list and editor panes must expose a vertical drag handle");
assert.ok(html.includes("layout-resizer horizontal"),
  "runtime content and log panes must expose a horizontal drag handle");
assert.ok(html.includes("startLayoutResize"),
  "drag handles must start pointer-driven layout resizing");
assert.ok(html.includes("smartkit.layout.leftWidth"),
  "the left/right layout size must persist across page switches");
assert.ok(html.includes("smartkit.layout.logHeight"),
  "the top/bottom layout size must persist across page switches");
assert.ok(html.includes('id="datasetName"'),
  "the dataset file information view must expose an editable dataset name");
assert.ok(html.includes("saveDatasetName"),
  "the dataset name editor must save through the production dataset API");
assert.ok(html.includes('onclick="openRenameDataset()"'),
  "the workbench header must expose an obvious dataset-name edit action");
assert.ok(!html.includes("setRuntimeTab('logs')"),
  "runtime logs must stay embedded below each simulator view instead of using a duplicate tab");
assert.ok(html.includes("editor-test-actions"),
  "SSH and REST test actions must be rendered inside the protocol editor");
assert.ok(html.includes("copySshTestCommand"),
  "the SSH editor must expose a working test-command copy action");
assert.ok(html.includes("testCurrentRoute"),
  "the REST editor must expose a working current-route test action");
assert.ok(html.includes("save-editor-action"),
  "editable SSH and REST forms must expose an enabled save action");

const elements = {};
const element = (id) => elements[id] ||= {id, innerHTML: "", value: "", classList: {add() {}, remove() {}}};
const calls = [];
const requests = [];
let clipboardText = "";
const context = {
  console,
  location: {search: "", href: ""},
  URLSearchParams,
  confirm: () => true,
  clearTimeout() {},
  setTimeout() {},
  navigator: {clipboard: {writeText: async (value) => { clipboardText = value; }}},
  document: {
    body: {appendChild() {}},
    getElementById: element,
    createElement: () => ({textContent: "", style: {}, classList: {add() {}, remove() {}}}),
    querySelector: () => null,
    querySelectorAll: () => [],
  },
  fetch: async (url, options = {}) => {
    calls.push(url);
    requests.push({url, options});
    const payload = url === "/api/dataset-directory"
      ? {path: "D:/datasets", dataset_count: 1, invalid_count: 0}
      : url.startsWith("/api/datasets?")
        ? {items: [{id: "normal", name: "正常设备", description: "", revision: 2,
                    command_count: 1, route_count: 1, filename: "normal.json"}],
           total: 1, page: 1, page_size: 8}
        : url === "/api/datasets/normal"
          ? {id: "normal", name: "正常设备", description: "", revision: 2,
             server: {username: "admin", password: "secret"}, commands: [{name: "show", output: "ok"}],
             rest_routes: [{method: "GET", uri: "/health", status_code: 200,
                            response_headers: {}, response_body: "ok"}]}
          : url === "/api/runtime/status" ? {status: "idle"}
          : url === "/api/services/status" ? {ssh: false, rest: false}
          : url === "/api/rest/test" ? {status: "ok", status_code: 200, elapsed_ms: 12,
              tls_version: "TLSv1.3", response_headers: [["Content-Type", "application/json"]],
              response_body: "ok"}
          : url === "/api/ssh/import-log/preview" ? {status: "ok",
              summary: {total: 2, importable: 1, duplicate: 1, incomplete: 0},
              commands: [
                {status: "ready", command: {name: "show imported", description: "从日志导入", group: "", output: "ok"}},
                {status: "duplicate", command: {name: "show", description: "从日志导入", group: "", output: "old"}},
              ]}
          : url === "/api/rest/import-log/preview" ? {status: "ok",
              summary: {total: 1, importable: 0, duplicate: 1, incomplete: 0},
              routes: [{status: "duplicate", route: {method: "GET", uri: "/health", group: "",
                status_code: 201, response_headers: {"Content-Type": "application/json"},
                response_body: "new response"}}]}
          : [];
    return {ok: true, status: 200, json: async () => payload};
  },
};

vm.createContext(context);
vm.runInContext(script, context);
setImmediate(async () => {
  assert.ok(element("root").innerHTML.includes("正常设备"));
  assert.ok(calls.includes("/api/dataset-directory"));
  assert.ok(calls.includes("/api/runtime/status"));
  assert.ok(calls.some(url => url.startsWith("/api/datasets?page=")));
  assert.ok(element("root").innerHTML.includes('onclick="openRenameDataset()"'));
  context.openCreate(true);
  assert.ok(element("modalRoot").innerHTML.includes('onclick="closeModal()">取消</button>'),
    "copy dialog cancel action must close the modal");
  assert.ok(!element("modalRoot").innerHTML.includes('onclick="openDatasetManager()">取消</button>'),
    "copy dialog cancel action must not open dataset management");
  context.closeModal();
  assert.strictEqual(element("modalRoot").innerHTML, "");
  await context.setWorktab("ssh");
  context.toggleEdit();
  assert.match(element("root").innerHTML, /save-editor-action" onclick="saveRevision\(\)" >保存数据集文件/,
    "save action must be enabled as soon as SSH or REST editing starts");
  await context.copySshTestCommand();
  assert.ok(clipboardText.includes("ssh -p"), "SSH test action must write a usable command");
  await context.setWorktab("rest");
  element("routeMethod").value = "GET";
  element("routeUri").value = "/health";
  await context.testCurrentRoute();
  assert.ok(calls.includes("/api/rest/test"), "REST test action must call the backend tester");
  assert.ok(element("modalRoot").innerHTML.includes("200"),
    "REST test action must display its response result");
  context.closeModal();
  await context.setWorktab("ssh");
  context.openSshLogImport();
  element("sshLogText").value = "Execute command line / Receive str";
  await context.previewSshLogImport();
  assert.ok(element("modalRoot").innerHTML.includes("show imported"));
  assert.ok(element("modalRoot").innerHTML.includes('class="ssh-command-choice" type="checkbox" value="1" >'),
    "duplicate SSH commands must be unchecked but selectable for explicit overwrite");
  element("sshLogImportGroup").value = "Imported";
  context.document.querySelectorAll = (selector) => selector === ".ssh-command-choice:checked"
    ? [{value: "0"}, {value: "1"}] : [];
  await context.confirmSshLogImport();
  const saveRequest = requests.findLast(request => request.url === "/api/datasets/normal"
    && request.options.method === "PUT");
  const savedDataset = JSON.parse(saveRequest.options.body);
  assert.ok(savedDataset.commands.some(command => command.name === "show imported"
    && command.group === "Imported"), "selected SSH commands must be saved in the target group");
  assert.strictEqual(savedDataset.commands.filter(command => command.name === "show").length, 1,
    "overwriting a duplicate SSH command must not append a second command");
  assert.ok(savedDataset.commands.some(command => command.name === "show"
    && command.output === "old" && command.group === "Imported"),
    "selected duplicate SSH command must replace the existing command");
  await context.setWorktab("rest");
  context.openLogImport();
  element("restLogText").value = "REST log";
  await context.previewLogImport();
  assert.ok(element("modalRoot").innerHTML.includes('class="log-route-choice" type="checkbox" value="0" >'),
    "duplicate REST routes must be unchecked but selectable for explicit overwrite");
  element("logImportGroup").value = "ImportedRest";
  context.document.querySelectorAll = (selector) => selector === ".log-route-choice:checked"
    ? [{value: "0"}] : [];
  await context.confirmLogImport();
  const restSaveRequest = requests.findLast(request => request.url === "/api/datasets/normal"
    && request.options.method === "PUT");
  const restSavedDataset = JSON.parse(restSaveRequest.options.body);
  assert.strictEqual(restSavedDataset.rest_routes.filter(route => route.method === "GET"
    && route.uri === "/health").length, 1, "overwriting a REST route must not append a duplicate");
  assert.ok(restSavedDataset.rest_routes.some(route => route.method === "GET" && route.uri === "/health"
    && route.status_code === 201 && route.response_body === "new response"
    && route.group === "ImportedRest"), "selected duplicate REST route must replace the existing route");
  console.log("production prototype-based UI syntax and bootstrap checks passed");
});

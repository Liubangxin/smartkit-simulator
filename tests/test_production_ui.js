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

const elements = {};
const element = (id) => elements[id] ||= {id, innerHTML: "", value: "", classList: {add() {}, remove() {}}};
const calls = [];
const context = {
  console,
  location: {search: "", href: ""},
  URLSearchParams,
  confirm: () => true,
  clearTimeout() {},
  setTimeout() {},
  document: {
    body: {appendChild() {}},
    getElementById: element,
    createElement: () => ({textContent: "", style: {}, classList: {add() {}, remove() {}}}),
    querySelector: () => null,
    querySelectorAll: () => [],
  },
  fetch: async (url) => {
    calls.push(url);
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
          : [];
    return {ok: true, status: 200, json: async () => payload};
  },
};

vm.createContext(context);
vm.runInContext(script, context);
setImmediate(() => {
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
  console.log("production prototype-based UI syntax and bootstrap checks passed");
});

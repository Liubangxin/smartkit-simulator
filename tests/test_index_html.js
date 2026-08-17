const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync("index.html", "utf8");
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];
const elements = {};

function element(id) {
  if (!elements[id]) {
    elements[id] = {
      id,
      value: "",
      textContent: "",
      innerHTML: "",
      disabled: false,
      appendChild() {},
      addEventListener() {},
      focus() {},
      dataset: {},
      style: {},
    };
  }
  return elements[id];
}

const context = {
  document: {
    getElementById(id) {
      return element(id);
    },
    querySelector() {
      return { offsetHeight: 0, style: {} };
    },
    querySelectorAll(selector) {
      return context.queryResults[selector] || [];
    },
    body: { classList: { add() {}, remove() {} } },
    createElement(tagName) {
      const created = { tagName: tagName.toUpperCase(), children: [], appendChild(child) { this.children.push(child); }, remove() {}, focus() {}, dataset: {}, style: {} };
      context.createdElements.push(created);
      return created;
    },
  },
  window: { innerHeight: 600, addEventListener() {} },
  navigator: { clipboard: { writeText(text) { context.clipboardText = text; return Promise.resolve(); } } },
  clipboardText: "",
  fetch(url, options) {
    context.fetchCalls.push({ url, options });
    if (url === "/api/rest/test") return Promise.resolve({ ok: true, json: () => Promise.resolve({
      status: "ok", status_code: 201, reason: "Created", elapsed_ms: 12.5, tls_version: "TLSv1.3",
      response_headers: [["Content-Type", "application/json"]], response_body: "{\"ok\":true}"
    }) });
    if (url === "/api/rest/import-log/preview") return Promise.resolve({ ok: true, json: () => Promise.resolve({
      status: "ok", summary: { total: 3, importable: 2, duplicate: 1, incomplete: 0 }, routes: [
        { status: "ready", route: { method: "GET", uri: "/redfish/v1/Chassis", status_code: 200, response_headers: {"Content-Type":"application/json"}, response_body: "{}" } },
        { status: "ready", route: { method: "GET", uri: "/redfish/v1/Managers", status_code: 200, response_headers: {"Content-Type":"application/json"}, response_body: "{}" } },
        { status: "duplicate", route: { method: "GET", uri: "/device", status_code: 200, response_headers: {}, response_body: "{}" } }
      ]
    }) });
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ server: {}, commands: [] }) });
  },
  fetchCalls: [],
  queryResults: {},
  createdElements: [],
  promptValue: null,
  prompt() {
    return context.promptValue;
  },
  confirm() {
    return true;
  },
  setTimeout() {},
  alert(message) {
    throw new Error(message);
  },
};

vm.createContext(context);
vm.runInContext(script.replace(/\ninit\(\);\s*$/, ""), context);
context.modalValue = null;
context.showModal = () => Promise.resolve(context.modalValue);

vm.runInContext(`config = {
  command_groups: ["System", "Empty Group"],
  rest_groups: ["Device"],
  rest_routes: [{ method: "GET", uri: "/device", group: "Device", status_code: 200, response_headers: {}, response_body: "{}" }],
  commands: [
    { name: "show system general", description: "general", group: "System", output: "old output" },
    { name: "new-command", description: "", output: "" },
    { name: "new-command-2", description: "", output: "" },
  ],
};`, context);

assert.strictEqual(context.commandNameExists(" show system general ", -1), true);
assert.strictEqual(context.commandNameExists("show system general", 0), false);
assert.strictEqual(context.commandNameExists("show system general", 1), true);
assert.strictEqual(context.nextCommandName("new-command"), "new-command-3");

context.selectCommand(0);
assert.strictEqual(elements.cmdName.disabled, true);
assert.strictEqual(elements.cmdDesc.disabled, true);
assert.strictEqual(elements.cmdGroup.disabled, true);
assert.strictEqual(elements.cmdOutput.disabled, true);
assert.strictEqual(elements.saveBtn.disabled, true);
assert.strictEqual(elements.editBtn.textContent, "Edit");

context.toggleEdit();
assert.strictEqual(elements.cmdName.disabled, false);
assert.strictEqual(elements.cmdDesc.disabled, false);
assert.strictEqual(elements.cmdGroup.disabled, false);
assert.strictEqual(elements.cmdOutput.disabled, false);
assert.strictEqual(elements.saveBtn.disabled, false);
assert.strictEqual(elements.editBtn.textContent, "Cancel");

assert.strictEqual(context.normalizedGroup({}), "Ungrouped");
assert.strictEqual(context.normalizedGroup({ group: " System " }), "System");
assert.deepStrictEqual(
  Array.from(context.normalizeGroupNames(["Empty"], [{ group: "System" }, { group: "System" }])),
  ["Empty", "System"]
);
assert.strictEqual(context.groupNameExists(["System"], " system "), true);
assert.strictEqual(context.validRouteUri("/redfish/v1/Sessions/{session_id}"), true);
assert.strictEqual(context.validRouteUri("/redfish/v1/Sessions/{session_id}/{session_id}"), false);
assert.strictEqual(context.validRouteUri("/redfish/v1/Sessions/{bad-name}"), false);
assert.ok(html.includes('onclick="openLogImport()"'));

elements.cmdOutput.value = "changed but cancelled";
context.toggleEdit();
assert.strictEqual(elements.cmdOutput.value, "old output");
assert.strictEqual(elements.cmdOutput.disabled, true);
assert.strictEqual(elements.saveBtn.disabled, true);
assert.strictEqual(elements.editBtn.textContent, "Edit");

context.newCommand();
assert.strictEqual(elements.cmdName.disabled, false);
assert.strictEqual(elements.saveBtn.disabled, false);
assert.strictEqual(elements.editBtn.textContent, "Cancel");

vm.runInContext(`isRestEditing = true`, context);
element("routeBody").value = '{"name":"OceanStor","items":[1,2]}';
context.formatResponseJson();
assert.strictEqual(element("routeBody").value, '{\n  "name": "OceanStor",\n  "items": [\n    1,\n    2\n  ]\n}');

element("bindAddress").value = "0.0.0.0";
element("port").value = "2222";
element("username").value = "admin";
element("password").value = "admin123";
context.startServer().then(() => {
  const startCall = context.fetchCalls.find((call) => call.url === "/api/server/start");
  assert.ok(startCall);
  assert.strictEqual(JSON.parse(startCall.options.body).bind_address, "0.0.0.0");
  assert.strictEqual(elements.sshServerToggle.textContent, "Stop Server");
  assert.strictEqual(elements.sshServerToggle.className, "btn-stop");
  vm.runInContext("selectedRestGroup = null", context);
  context.openLogImport();
  assert.strictEqual(elements.importTargetGroup.value, "");
  vm.runInContext("selectedRestGroup = 'Device'", context);
  context.openLogImport();
  assert.strictEqual(elements.importTargetGroup.value, "Device");
  elements.importLogText.value = "##url : /redfish/v1/Chassis ##method : GET";
  return context.previewLogImport();
}).then(() => {
  const previewCall = context.fetchCalls.find((call) => call.url === "/api/rest/import-log/preview");
  assert.ok(previewCall);
  assert.strictEqual(JSON.parse(previewCall.options.body).log_text, "##url : /redfish/v1/Chassis ##method : GET");
  assert.strictEqual(vm.runInContext("logImportResults.length", context), 3);
  const firstRouteCheckbox = context.createdElements.find(created => created.tagName === "INPUT" && created.dataset.index === 0);
  const firstRouteRow = context.createdElements.find(created => created.children.includes(firstRouteCheckbox));
  firstRouteCheckbox.checked = true;
  firstRouteRow.onclick({ target: firstRouteRow });
  assert.strictEqual(firstRouteCheckbox.checked, false, "clicking an importable route row must toggle its checkbox");
  context.setAllLogImportRoutes(false);
  assert.strictEqual(vm.runInContext("logImportResults.filter(item => item.status === 'ready').every(item => !item.selected)", context), true);
  context.setAllLogImportRoutes(true);
  assert.strictEqual(vm.runInContext("logImportResults.filter(item => item.status === 'ready').every(item => item.selected)", context), true);
  const pageRoutes = Array.from({length: 12}, (_value, index) => ({status:"ready", route:{method:"GET", uri:"/page/" + index, status_code:200, response_headers:{}, response_body:"{}"}}));
  context.renderLogImportResults({summary:{total:12, importable:12, duplicate:0, incomplete:0}, routes:pageRoutes});
  assert.strictEqual(elements.importPageStatus.textContent, "Page 1 of 2 (12 routes)");
  const pagedCheckbox = context.createdElements.filter(created => created.tagName === "INPUT" && created.dataset.index === 0).at(-1);
  const pagedRow = context.createdElements.findLast(created => created.children.includes(pagedCheckbox));
  pagedRow.onclick({target:pagedRow});
  context.changeLogImportPage(1);
  assert.strictEqual(elements.importPageStatus.textContent, "Page 2 of 2 (12 routes)");
  context.changeLogImportPage(-1);
  const rerenderedCheckbox = context.createdElements.filter(created => created.tagName === "INPUT" && created.dataset.index === 0).at(-1);
  assert.strictEqual(rerenderedCheckbox.checked, false, "route selection must persist across pages");
  return context.previewLogImport();
}).then(() => {
  elements.importTargetGroup.value = "";
  vm.runInContext("logImportResults.forEach((item, index) => item.selected = index === 0)", context);
  return context.confirmLogImport();
}).then(() => {
  const imported = vm.runInContext("config.rest_routes.find(route => route.uri === '/redfish/v1/Chassis')", context);
  assert.strictEqual(imported.group, "");
  assert.strictEqual(vm.runInContext("config.rest_routes.some(route => route.uri === '/redfish/v1/Managers')", context), false);
  assert.strictEqual(vm.runInContext("config.rest_routes.filter(route => route.uri === '/device').length", context), 1);
  vm.runInContext("selectedCommandGroup = null; selectedIdx = -1", context);
  elements.cmdGroup.value = "System";
  context.modalValue = "Hardware";
  return context.renameGroup("command");
}).then(() => {
  assert.deepStrictEqual(Array.from(vm.runInContext("config.command_groups", context)), ["Hardware", "Empty Group"]);
  assert.strictEqual(vm.runInContext("config.commands[0].group", context), "Hardware");
  assert.strictEqual(elements.cmdGroup.value, "Hardware");
  context.selectRoute(0);
  context.modalValue = "Platform APIs";
  return context.renameGroup("rest");
}).then(() => {
  assert.deepStrictEqual(Array.from(vm.runInContext("config.rest_groups", context)), ["Platform APIs"]);
  assert.strictEqual(vm.runInContext("config.rest_routes[0].group", context), "Platform APIs");
  assert.strictEqual(elements.routeGroup.value, "Platform APIs");
  context.selectCommand(0);
  context.modalValue = "Empty Group";
  return context.moveItem("command");
}).then(() => {
  assert.strictEqual(vm.runInContext("config.commands[0].group", context), "Empty Group");
  context.selectRoute(0);
  context.modalValue = "";
  return context.moveItem("rest");
}).then(() => {
  assert.strictEqual(vm.runInContext("config.rest_routes[0].group", context), "");
  element("restBindAddress").value = "0.0.0.0";
  element("restPort").value = "8080";
  vm.runInContext("restRunning = true", context);
  return context.openApiTester();
}).then(() => {
  assert.strictEqual(elements.testerMethod.value, "GET");
  assert.strictEqual(elements.testerUrl.value, "https://127.0.0.1:8080/device");
  assert.strictEqual(JSON.stringify(context.parseTesterHeaders("Content-Type: application/json\nX-Test: yes")), '{"Content-Type":"application/json","X-Test":"yes"}');
  elements.testerMethod.value = "POST";
  elements.testerHeaders.value = "Content-Type: application/json\nX-Test: yes";
  elements.testerBody.value = '{"name":"O\'Brien"}';
  return context.copyTesterCurl();
}).then(() => {
  assert.ok(context.clipboardText.includes("curl.exe -k -X POST 'https://127.0.0.1:8080/device'"));
  assert.ok(context.clipboardText.includes("-H 'Content-Type: application/json'"));
  assert.ok(context.clipboardText.includes("--data-raw '{\"name\":\"O''Brien\"}'"));
  return context.sendApiTest();
}).then(() => {
  assert.strictEqual(elements.testerResponseBody.textContent, '{"ok":true}');
  assert.ok(elements.testerResponseSummary.innerHTML.includes("TLSv1.3"));
  return context.toggleSshServer();
}).then(() => {
  assert.strictEqual(elements.sshServerToggle.textContent, "Start Server");
  assert.strictEqual(elements.sshServerToggle.className, "btn-start");
  return context.toggleRestServer();
}).then(() => {
  assert.strictEqual(elements.restServerToggle.textContent, "Start REST");
  assert.strictEqual(elements.restServerToggle.className, "btn-start");
  console.log("index.html command editor tests passed");
}).catch((error) => {
  console.error(error);
  process.exit(1);
});

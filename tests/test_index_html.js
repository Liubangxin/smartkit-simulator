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
    querySelectorAll() {
      return [];
    },
    body: { classList: { add() {}, remove() {} } },
    createElement() {
      return { appendChild() {}, remove() {}, style: {} };
    },
  },
  window: { innerHeight: 600, addEventListener() {} },
  fetch(url, options) {
    context.fetchCalls.push({ url, options });
    return Promise.resolve({ json: () => Promise.resolve({ server: {}, commands: [] }) });
  },
  fetchCalls: [],
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
  console.log("index.html command editor tests passed");
}).catch((error) => {
  console.error(error);
  process.exit(1);
});

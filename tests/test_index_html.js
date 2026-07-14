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
    body: { classList: { add() {}, remove() {} } },
    createElement() {
      return {};
    },
  },
  window: { innerHeight: 600, addEventListener() {} },
  fetch() {
    return Promise.resolve({ json: () => Promise.resolve({ server: {}, commands: [] }) });
  },
  setTimeout() {},
};

vm.createContext(context);
vm.runInContext(script.replace(/\ninit\(\);\s*$/, ""), context);

vm.runInContext(`config = {
  commands: [
    { name: "show system general", description: "general", output: "old output" },
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
assert.strictEqual(elements.cmdOutput.disabled, true);
assert.strictEqual(elements.saveBtn.disabled, true);
assert.strictEqual(elements.editBtn.textContent, "Edit");

context.toggleEdit();
assert.strictEqual(elements.cmdName.disabled, false);
assert.strictEqual(elements.cmdDesc.disabled, false);
assert.strictEqual(elements.cmdOutput.disabled, false);
assert.strictEqual(elements.saveBtn.disabled, false);
assert.strictEqual(elements.editBtn.textContent, "Cancel");

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

console.log("index.html command editor tests passed");

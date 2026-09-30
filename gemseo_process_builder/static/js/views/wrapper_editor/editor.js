// @ts-check
// The executable wrapper editor (SPEC § 7.5): a center tab wrapping an external
// code graphically, from sample input and output files.
//
// The editor works on a copy of the wrapper spec, as stored in a descriptor
// but with the templates inline. "Apply" gives it to the component (its
// configuration and ports change in one undo step); "Save as descriptor"
// writes a reusable ``.gpbwrap.json`` file.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { askConfirmation } from "../../components/modal.js";
import { CommandTab } from "./command_tab.js";
import { button } from "./fields.js";
import { InputsTab } from "./inputs_tab.js";
import { OutputsTab } from "./outputs_tab.js";
import { TestRunTab } from "./test_run_tab.js";

const DESCRIPTOR_FILTER = "Wrapper descriptors (*.gpbwrap.json)";
const TABS = [
  { id: "command", label: "Command" },
  { id: "inputs", label: "Inputs" },
  { id: "outputs", label: "Outputs" },
  { id: "test", label: "Test run" },
];

/** @type {Map<string, WrapperEditor>} */
const opened = new Map();
let newCount = 0;

/** A wrapper without anything yet. */
function emptySpec(name = "Wrapper") {
  return { name, command: "", inputs: [], outputs: [], templates: [], rules: [] };
}

export class WrapperEditor {
  /**
   * @param {HTMLElement} page
   * @param {{nodeId: string | null, spec: any, baseFolder: string, descriptorPath: string}} state
   */
  constructor(page, { nodeId, spec, baseFolder, descriptorPath }) {
    this.page = page;
    /** The component using the wrapper, if any. */
    this.nodeId = nodeId;
    this.spec = spec;
    /** The folder the relative paths of the spec refer to. */
    this.baseFolder = baseFolder;
    /** The descriptor used by the component (edits are saved into it). */
    this.descriptorPath = descriptorPath;
    /** @type {Record<string, string>} - Sample outputs by file name ("stdout" too). */
    this.outputSamples = {};
    this.dirty = false;
    this.view = "command";

    this.title = el("span.wrapper-title");
    this.status = el("span.wrapper-status");
    this.actions = el("div.wrapper-actions");
    this.bar = el("div.results-tabs");
    /** @type {Record<string, HTMLElement>} */
    this.pages = Object.fromEntries(TABS.map((tab) => [tab.id, el("div.results-page.wrapper-page")]));
    /** @type {Record<string, {render: () => void}>} */
    this.tabs = {
      command: new CommandTab(this.pages.command, this),
      inputs: new InputsTab(this.pages.inputs, this),
      outputs: new OutputsTab(this.pages.outputs, this),
      test: new TestRunTab(this.pages.test, this),
    };
    page.classList.add("results-tab", "wrapper-editor");
    page.replaceChildren(el("div.wrapper-header", {}, [this.title, this.status, this.actions]), this.bar, ...Object.values(this.pages));
    this.show("command");
    this.renderHeader();
  }

  /** @param {string} view */
  show(view) {
    this.view = view;
    this.bar.replaceChildren(
      ...TABS.map((tab) => el(`button.driver-tab-button${tab.id === view ? ".active" : ""}`, { text: tab.label, onClick: () => this.show(tab.id) })),
    );
    for (const [id, element] of Object.entries(this.pages)) {
      element.hidden = id !== view;
    }
    this.tabs[view].render();
  }

  /** The spec changed: mark it unsaved and show it again. */
  changed() {
    this.dirty = true;
    this.renderHeader();
    this.tabs[this.view].render();
  }

  get node() {
    return this.nodeId ? app.store.node(this.nodeId) : null;
  }

  renderHeader() {
    const node = this.node;
    this.title.textContent = `${this.spec.name || "Wrapper"}${this.dirty ? " •" : ""}`;
    this.status.textContent = this.descriptorPath
      ? `Descriptor ${this.descriptorPath}`
      : node
        ? `Wrapper of ${node.name}`
        : "Not used in the model";
    /** @type {HTMLElement[]} */
    const actions = [];
    if (this.descriptorPath) {
      actions.push(button("Save descriptor", () => this.saveDescriptor(), { primary: true, title: "Save the changes into the descriptor" }));
      if (node) {
        actions.push(button("Detach from descriptor", () => this.detach(), { title: "Keep a copy of the wrapper in the component only" }));
      }
    } else if (node) {
      actions.push(button("Apply to component", () => this.apply(), { primary: true, title: "Update the configuration and variables of the component" }));
    } else {
      actions.push(button("Add to model", () => this.addToModel(), { primary: true, title: "Add a component running this wrapper at the level shown" }));
      actions.push(button("Open descriptor…", () => this.openDescriptor()));
    }
    actions.push(button("Save as descriptor…", () => this.saveAs(), { title: "Save a reusable .gpbwrap.json file" }));
    this.actions.replaceChildren(...actions);
  }

  /** Give the edited wrapper to the component. */
  async apply() {
    try {
      await app.api.call("executable.apply", { id: this.nodeId, spec: this.spec, base_folder: this.baseFolder });
      this.dirty = false;
      this.renderHeader();
    } catch (error) {
      showError("The wrapper could not be applied", error);
    }
  }

  async addToModel() {
    try {
      this.nodeId = await app.api.call("executable.add", { parent: app.navigation.current(), spec: this.spec, base_folder: this.baseFolder });
      this.dirty = false;
      this.renderHeader();
      app.selection.set([/** @type {string} */ (this.nodeId)]);
    } catch (error) {
      showError("The component could not be added", error);
    }
  }

  async saveDescriptor() {
    try {
      await app.api.call("executable.saveDescriptor", { path: this.descriptorPath, spec: this.spec, base_folder: this.baseFolder });
      if (this.nodeId) {
        await app.api.call("executable.apply", { id: this.nodeId, descriptor_path: this.descriptorPath });
      }
      this.dirty = false;
      this.renderHeader();
    } catch (error) {
      showError("The descriptor could not be saved", error);
    }
  }

  async saveAs() {
    const prefs = await app.api.call("prefs.get");
    const folder = prefs.catalog_paths?.[0] ?? "";
    const suggested = `${this.spec.name || "wrapper"}.gpbwrap.json`;
    const path = await app.api.call("dialog.saveFile", {
      title: "Save the wrapper as a descriptor",
      filter: DESCRIPTOR_FILTER,
      start: folder ? `${folder}/${suggested}` : suggested,
    });
    if (!path) {
      return;
    }
    try {
      const saved = await app.api.call("executable.saveDescriptor", { path, spec: this.spec, base_folder: this.baseFolder });
      app.api.call("catalog.refresh").catch(() => {});
      const node = this.node;
      if (node && (await askConfirmation("Use the descriptor", `Make ${node.name} use ${saved}? Later changes of the descriptor will apply to it.`, "Use it"))) {
        await app.api.call("executable.apply", { id: this.nodeId, descriptor_path: saved });
        this.descriptorPath = saved;
        this.dirty = false;
      }
      this.renderHeader();
      this.status.textContent = `Saved in ${saved}`;
    } catch (error) {
      showError("The descriptor could not be saved", error);
    }
  }

  /** Keep the wrapper in the component: later changes stay out of the descriptor. */
  async detach() {
    try {
      const { spec, base_folder: baseFolder } = await app.api.call("executable.loadDescriptor", { path: this.descriptorPath });
      if (!this.dirty) {
        this.spec = spec;
      }
      this.baseFolder = this.baseFolder || baseFolder;
      await app.api.call("executable.apply", { id: this.nodeId, spec: this.spec, base_folder: this.baseFolder });
      this.descriptorPath = "";
      this.dirty = false;
      this.renderHeader();
    } catch (error) {
      showError("The wrapper could not be detached", error);
    }
  }

  async openDescriptor() {
    const path = await app.api.call("dialog.openFile", { title: "Wrapper descriptor", filter: DESCRIPTOR_FILTER });
    if (!path) {
      return;
    }
    try {
      const { spec, base_folder: baseFolder } = await app.api.call("executable.loadDescriptor", { path });
      Object.assign(this, { spec, baseFolder, descriptorPath: path, dirty: false });
      this.renderHeader();
      this.show(this.view);
    } catch (error) {
      showError("The descriptor could not be opened", error);
    }
  }
}

/**
 * The state of the editor of a component: its descriptor or its inline wrapper.
 *
 * @param {any} node
 */
async function componentState(node) {
  const config = node.config ?? {};
  if (config.descriptor_path) {
    const { spec, base_folder: baseFolder } = await app.api.call("executable.loadDescriptor", { path: config.descriptor_path });
    return { nodeId: node.id, spec, baseFolder, descriptorPath: config.descriptor_path };
  }
  const spec = structuredClone(config.spec ?? emptySpec(node.name));
  const baseFolder = config.base_folder_path ?? "";
  // Template files of an inline wrapper are read to be edited inline.
  for (const template of spec.templates ?? []) {
    if (template.content === undefined && template.template) {
      const path = baseFolder ? `${baseFolder}/${template.template}` : template.template;
      const { text } = await app.api.call("executable.readSample", { path });
      template.content = text;
      delete template.template;
    }
  }
  return { nodeId: node.id, spec, baseFolder, descriptorPath: "" };
}

/**
 * Open the wrapper editor of a component, or of a new wrapper.
 *
 * @param {string | null} [nodeId]
 */
export async function openWrapperEditor(nodeId = null) {
  const key = nodeId ?? `new-${++newCount}`;
  const existing = opened.get(key);
  if (existing) {
    app.tabs.center.activate(`wrapper-${key}`);
    return existing;
  }
  const node = nodeId ? app.store.node(nodeId) : null;
  let state;
  try {
    state = node ? await componentState(node) : { nodeId: null, spec: emptySpec(), baseFolder: "", descriptorPath: "" };
  } catch (error) {
    showError("The wrapper could not be read", error);
    return null;
  }
  const page = app.tabs.center.open({
    id: `wrapper-${key}`,
    title: node ? `Wrapper: ${node.name}` : "New wrapper",
    onClose: () => opened.delete(key),
  });
  const editor = new WrapperEditor(page, state);
  opened.set(key, editor);
  return editor;
}

export function installWrapperEditor() {
  app.actions.handle("tools.newWrapper", { run: () => openWrapperEditor() });
}

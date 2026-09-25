// @ts-check
// The inspector: properties and variables of the selected node.
import { app } from "../app.js";
import { el } from "../components/dom.js";
import { EditableTable } from "../components/editable_table.js";
import { showError } from "../components/errors.js";
import { unitList } from "../components/unit_input.js";
import { formatShape, formatValue, parseShape, parseValue } from "../lib/table_model.js";
import { INTROSPECTED_KINDS, componentConfigSection } from "./inspector_component.js";
import { DriverEditor } from "./driver_editor/index.js";
import { linkSection } from "./inspector_link.js";
import { terminalSection } from "../views/canvas/terminals.js";

const DTYPES = ["float", "int", "complex", "str", "path", "object"];
const MODES = [
  ["auto", "Automatic (MDA if there are loops)"],
  ["chain", "Chain, in order"],
  ["parallel", "Parallel"],
  ["mda", "MDA"],
];
const TYPE_LABELS = {
  component: "Component",
  assembly: "Assembly",
  driver: "Driver",
};

/**
 * Send a command, reporting errors in a dialog.
 *
 * @param {object} command
 * @param {string} failure
 */
function execute(command, failure) {
  return app.store.execute(command).catch((error) => {
    showError(failure, error);
    throw error;
  });
}

/**
 * A labelled row of the properties form.
 *
 * @param {string} label
 * @param {Node} control
 */
function field(label, control) {
  return el("label.form-row", {}, [el("span.form-label", { text: label }), control]);
}

export class InspectorPanel {
  /** @param {HTMLElement} root */
  constructor(root) {
    this.root = root;
    /** @type {string} */
    this.shownKey = "";
    /** @type {EditableTable | null} */
    this.variables = null;
    /** @type {Map<string, any>} */
    this.resolved = new Map();
    /** @type {DriverEditor | null} */
    this.driverEditor = null;
    app.selection.onChange(() => this.render());
    app.navigation.onChange(() => this.render());
    app.linkFocus.onChange(() => this.render());
    app.api.on("resolution.updated", () => this.loadResolved());
    app.store.subscribe(() => this.update());
    app.driverRoles.onChange(() => {
      const node = this.variables && app.store.node(this.target() ?? "");
      if (node) {
        this.variables?.setRows(this.variableRows(node));
      }
    });
    this.render();
  }

  /** The node shown: the single selected node, or the current level. */
  target() {
    const ids = app.selection.list();
    return ids.length === 1 ? ids[0] : ids.length === 0 ? app.navigation.current() : null;
  }

  /**
   * What the inspector shows of a node: it is built again when this changes.
   * The file and class of a Python component change its section (creating a
   * file, the table of its variables).
   *
   * @param {string} id
   * @param {any} node
   */
  keyOf(id, node) {
    const file = node.type === "component" ? JSON.stringify([node.config?.module_path, node.config?.module, node.config?.class]) : "";
    return `${id}:${node.type}:${node.kind ?? ""}:${file}`;
  }

  /** Re-render after a document change, keeping the variables table if possible. */
  update() {
    const id = this.target();
    const node = id ? app.store.node(id) : null;
    if (!node) {
      this.render();
      return;
    }
    const key = this.keyOf(id, node);
    if (key === this.shownKey && this.variables) {
      this.refreshProperties(node);
      this.variables.setRows(this.variableRows(node));
      return;
    }
    if (key === this.shownKey && this.driverEditor) {
      this.refreshProperties(node);
      this.driverEditor.update(node);
      return;
    }
    this.render();
  }

  /** Load the global names and couplings of the shown component. */
  async loadResolved() {
    const id = this.target();
    if (!id || app.store.node(id)?.type !== "component") {
      return;
    }
    try {
      const { ports } = await app.api.call("resolve.node", { id });
      this.resolved = new Map(ports.map((/** @type {any} */ port) => [`${port.direction}/${port.name}`, port]));
    } catch (error) {
      console.error(error);
      return;
    }
    const node = app.store.node(id);
    if (this.variables && node) {
      this.variables.setRows(this.variableRows(node));
    }
  }

  render() {
    const ids = app.selection.list();
    this.variables = null;
    this.driverEditor = null;
    const focus = /** @type {any} */ (app.linkFocus.link);
    if (!ids.length && focus?.terminal) {
      this.shownKey = "";
      this.root.replaceChildren(terminalSection(focus.terminal, focus.level));
      return;
    }
    if (!ids.length && focus) {
      this.shownKey = "";
      this.root.replaceChildren(linkSection(focus));
      return;
    }
    if (ids.length > 1) {
      this.shownKey = "";
      this.root.replaceChildren(
        el("div.inspector-section", {}, [el("p.placeholder", { text: `${ids.length} nodes selected.` })]),
      );
      return;
    }
    const id = /** @type {string} */ (this.target());
    const node = app.store.node(id);
    if (!node) {
      this.root.replaceChildren();
      return;
    }
    this.shownKey = this.keyOf(id, node);
    this.properties = el("div.inspector-section");
    this.root.replaceChildren(this.properties);
    this.refreshProperties(node);
    if (node.type === "component") {
      const config = componentConfigSection(node);
      if (config) {
        this.root.append(config);
      }
      this.root.append(this.variablesSection(node));
      this.loadResolved();
    } else if (node.type === "driver") {
      this.driverEditor = new DriverEditor(node);
      this.root.append(el("div.inspector-section.inspector-driver", {}, [this.driverEditor.root]));
    }
  }

  /** @param {any} node */
  refreshProperties(node) {
    if (!this.properties) {
      return;
    }
    const isRoot = node.id === app.store.rootId;
    const rows = [el("h3.section-title", { text: "Properties" })];
    const nameInput = /** @type {HTMLInputElement} */ (
      el("input.input", { type: "text", value: node.name, disabled: isRoot })
    );
    nameInput.addEventListener("change", () => {
      execute({ type: "renameNode", id: node.id, name: nameInput.value.trim() }, "The node could not be renamed").catch(
        () => {
          nameInput.value = node.name;
        },
      );
    });
    rows.push(field("Name", nameInput));
    const typeText = TYPE_LABELS[/** @type {keyof TYPE_LABELS} */ (node.type)] + (node.kind ? ` — ${node.kind}` : "");
    rows.push(field("Type", el("span.form-value", { text: typeText })));

    const description = /** @type {HTMLTextAreaElement} */ (el("textarea.input.form-textarea", { rows: 2 }));
    description.value = node.description ?? "";
    description.addEventListener("change", () =>
      execute(
        { type: "setNodeProperties", id: node.id, values: { description: description.value } },
        "The description could not be changed",
      ),
    );
    rows.push(field("Description", description));

    if (node.type === "assembly") {
      const mode = /** @type {HTMLSelectElement} */ (
        el(
          "select.select",
          {},
          MODES.map(([value, label]) => el("option", { value, text: label, selected: node.mode === value })),
        )
      );
      mode.addEventListener("change", () =>
        execute(
          { type: "setNodeProperties", id: node.id, values: { mode: mode.value } },
          "The execution mode could not be changed",
        ),
      );
      rows.push(field("Execution", mode));
      if (!isRoot) {
        rows.push(this.checkbox(node, "transparent", "Flatten into the parent driver"));
      }
    }
    if ((node.type === "component" || node.type === "assembly") && !isRoot) {
      rows.push(this.checkbox(node, "isolated", "Isolate variable names (namespace)"));
    }
    this.properties.replaceChildren(...rows);
  }

  /**
   * @param {any} node
   * @param {string} key
   * @param {string} label
   */
  checkbox(node, key, label) {
    const box = /** @type {HTMLInputElement} */ (el("input", { type: "checkbox", checked: Boolean(node[key]) }));
    box.addEventListener("change", () =>
      execute({ type: "setNodeProperties", id: node.id, values: { [key]: box.checked } }, "The property could not be changed"),
    );
    return el("label.form-row.form-check", {}, [box, el("span", { text: label })]);
  }

  /** @param {any} node */
  variableRows(node) {
    return (node.ports ?? []).map((/** @type {any} */ port, /** @type {number} */ index) => ({
      key: `${port.direction}/${port.local_name}`,
      index,
      port,
    }));
  }

  /**
   * Replace one port and send the whole list.
   *
   * @param {any} node
   * @param {number} index
   * @param {object | null} values - New values, or null to delete the port.
   */
  setPort(node, index, values) {
    const ports = node.ports.map((/** @type {any} */ port) => ({ ...port }));
    if (values === null) {
      ports.splice(index, 1);
    } else {
      ports[index] = { ...ports[index], ...values };
    }
    return app.store.execute({ type: "setPorts", id: node.id, ports });
  }

  /** @param {any} node */
  addPort(node) {
    const taken = new Set(node.ports.filter((/** @type {any} */ port) => port.direction === "in").map((/** @type {any} */ port) => port.local_name));
    let index = 1;
    while (taken.has(`x${index}`)) {
      index += 1;
    }
    execute(
      { type: "setPorts", id: node.id, ports: [...node.ports, { local_name: `x${index}`, direction: "in" }] },
      "The variable could not be added",
    );
  }

  /** @param {any} node */
  variablesSection(node) {
    // The variables of introspected components come from their configuration:
    // only their unit, default value and description are edited here.
    const derived = INTROSPECTED_KINDS.has(node.kind);
    const section = el("div.inspector-section.inspector-variables", {}, [
      el("div.section-header", {}, [
        el("h3.section-title", { text: "Variables" }),
        derived
          ? null
          : el("button.button.bordered", { text: "Add variable", onClick: () => this.addPort(app.store.node(node.id)) }),
      ]),
    ]);
    const current = () => app.store.node(node.id);
    const structural = () => !derived;
    /** @type {import("../components/editable_table.js").Column[]} */
    const columns = [
      {
        key: "name",
        editable: structural,
        title: "Name",
        width: 110,
        get: (row) => row.port.local_name,
        editor: "text",
        parse: (text) => ({ value: text.trim(), error: text.trim() ? null : "The name cannot be empty." }),
      },
      { key: "direction", title: "Dir.", width: 44, get: (row) => row.port.direction, editor: "select", options: ["in", "out"], editable: structural },
      { key: "dtype", title: "Type", width: 64, get: (row) => row.port.dtype ?? "float", editor: "select", options: DTYPES, editable: structural },
      {
        key: "shape",
        editable: structural,
        title: "Shape",
        width: 60,
        get: (row) => formatShape(row.port.shape ?? []),
        editor: "text",
        parse: (text) => parseShape(text),
      },
      {
        key: "unit",
        title: "Unit",
        width: 60,
        get: (row) => row.port.unit ?? "",
        editor: "text",
        datalist: unitList(),
        parse: (text) => ({ value: text.trim() || null, error: null }),
      },
      {
        key: "flatten",
        title: "1-D",
        width: 34,
        get: (row) => Boolean(row.port.flatten),
        editor: "checkbox",
        // Only arrays of 2 dimensions or more are flattened.
        editable: (row) => (row.port.shape ?? []).length >= 2,
      },
      {
        key: "default",
        title: "Default",
        width: 80,
        get: (row) => row.port.default_text ?? formatValue(row.port.default),
        editor: "text",
        parse: (text) => parseValue(text),
      },
      {
        key: "global",
        title: "Global name",
        width: 110,
        get: (row) => this.resolved.get(row.key)?.global_name ?? row.port.global_name ?? "",
        format: (row) => {
          const resolved = this.resolved.get(row.key);
          const name = resolved?.global_name ?? row.port.global_name ?? "";
          return resolved?.source === "override" ? `${name} (set)` : name;
        },
        editor: "text",
        parse: (text) => ({ value: text.trim().replace(/ \(set\)$/, "") || null, error: null }),
      },
      {
        key: "coupled",
        title: "Coupled with",
        width: 110,
        get: (row) =>
          (this.resolved.get(row.key)?.partners ?? [])
            .map((/** @type {string} */ id) => app.store.node(id)?.name ?? "?")
            .join(", "),
      },
      {
        key: "role",
        title: "Role",
        width: 110,
        get: (row) => app.driverRoles.of(node.id, row.port.direction, row.port.local_name).join(", "),
      },
      { key: "description", title: "Description", width: 140, get: (row) => row.port.description ?? "", editor: "text" },
      { key: "remove", title: "Remove", width: 28, get: () => "", editor: "button", buttonText: "×", editable: structural },
    ];
    /** @type {Record<string, string>} */
    const fieldOf = { name: "local_name", direction: "direction", dtype: "dtype", shape: "shape", unit: "unit", description: "description" };
    this.variables = new EditableTable(section, {
      columns,
      onEdit: (row, column, value) => {
        if (column.key === "global") {
          return app.store.execute({
            type: "setGlobalName",
            id: node.id,
            port: row.port.local_name,
            direction: row.port.direction,
            global_name: value,
          });
        }
        if (column.key === "flatten") {
          return app.store.execute({
            type: "setPortOptions",
            id: node.id,
            port: row.port.local_name,
            direction: row.port.direction,
            values: { flatten: value },
          });
        }
        if (column.key === "remove") {
          return this.setPort(current(), row.index, null);
        }
        if (column.key === "default") {
          return this.setPort(current(), row.index, { default: value, default_text: formatValue(value) || null });
        }
        return this.setPort(current(), row.index, { [fieldOf[column.key]]: value });
      },
    });
    this.variables.setRows(this.variableRows(node));
    return section;
  }
}

// @ts-check
// The inspector: properties and variables of the selected node.
import { app } from "../app.js";
import { el } from "../components/dom.js";
import { EditableTable } from "../components/editable_table.js";
import { showError } from "../components/errors.js";
import { formatShape, formatValue, parseShape, parseValue } from "../lib/table_model.js";

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
    app.selection.onChange(() => this.render());
    app.navigation.onChange(() => this.render());
    app.store.subscribe(() => this.update());
    this.render();
  }

  /** The node shown: the single selected node, or the current level. */
  target() {
    const ids = app.selection.list();
    return ids.length === 1 ? ids[0] : ids.length === 0 ? app.navigation.current() : null;
  }

  /** Re-render after a document change, keeping the variables table if possible. */
  update() {
    const id = this.target();
    const node = id ? app.store.node(id) : null;
    if (!node) {
      this.render();
      return;
    }
    const key = `${id}:${node.type}:${node.kind ?? ""}`;
    if (key === this.shownKey && this.variables) {
      this.refreshProperties(node);
      this.variables.setRows(this.variableRows(node));
      return;
    }
    this.render();
  }

  render() {
    const ids = app.selection.list();
    this.variables = null;
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
    this.shownKey = `${id}:${node.type}:${node.kind ?? ""}`;
    this.properties = el("div.inspector-section");
    this.root.replaceChildren(this.properties);
    this.refreshProperties(node);
    if (node.type === "component") {
      this.root.append(this.variablesSection(node));
    } else if (node.type === "driver") {
      this.root.append(
        el("div.inspector-section", {}, [
          el("h3.section-title", { text: "Driver" }),
          el("p.placeholder", { text: "The driver editor is implemented in plan 15." }),
        ]),
      );
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
    const section = el("div.inspector-section.inspector-variables", {}, [
      el("div.section-header", {}, [
        el("h3.section-title", { text: "Variables" }),
        el("button.button.bordered", { text: "Add variable", onClick: () => this.addPort(app.store.node(node.id)) }),
      ]),
    ]);
    const current = () => app.store.node(node.id);
    /** @type {import("../components/editable_table.js").Column[]} */
    const columns = [
      {
        key: "name",
        title: "Name",
        width: 110,
        get: (row) => row.port.local_name,
        editor: "text",
        parse: (text) => ({ value: text.trim(), error: text.trim() ? null : "The name cannot be empty." }),
      },
      { key: "direction", title: "Dir.", width: 44, get: (row) => row.port.direction, editor: "select", options: ["in", "out"] },
      { key: "dtype", title: "Type", width: 64, get: (row) => row.port.dtype ?? "float", editor: "select", options: DTYPES },
      {
        key: "shape",
        title: "Shape",
        width: 60,
        get: (row) => formatShape(row.port.shape ?? []),
        editor: "text",
        parse: (text) => parseShape(text),
      },
      { key: "unit", title: "Unit", width: 60, get: (row) => row.port.unit ?? "", editor: "text", parse: (text) => ({ value: text.trim() || null, error: null }) },
      {
        key: "default",
        title: "Default",
        width: 80,
        get: (row) => row.port.default_text ?? formatValue(row.port.default),
        editor: "text",
        parse: (text) => parseValue(text),
      },
      { key: "description", title: "Description", width: 140, get: (row) => row.port.description ?? "", editor: "text" },
      { key: "remove", title: "Remove", width: 28, get: () => "", editor: "button", buttonText: "×" },
    ];
    /** @type {Record<string, string>} */
    const fieldOf = { name: "local_name", direction: "direction", dtype: "dtype", shape: "shape", unit: "unit", description: "description" };
    this.variables = new EditableTable(section, {
      columns,
      onEdit: (row, column, value) => {
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

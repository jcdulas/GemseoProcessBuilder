// @ts-check
// Tabs choosing the outputs a driver looks at: objectives, constraints, observables, responses.
import { el } from "../../components/dom.js";
import { EditableTable } from "../../components/editable_table.js";
import { parseValue } from "../../lib/table_model.js";
import { pickButton, replaced, setConfig, tabHeader } from "./common.js";

/**
 * @typedef {object} OutputTabOptions
 * @property {"objectives" | "constraints" | "observables" | "responses"} field
 * @property {string} hint
 * @property {string} button
 * @property {import("../../components/editable_table.js").Column[]} columns - Besides the variable.
 * @property {(name: string) => any} create - A new item for a picked variable.
 * @property {(item: any, key: string, value: any) => any} [apply] - The item with an edited cell.
 */

/**
 * A tab listing outputs of the driver scope.
 *
 * @param {import("./common.js").TabContext} context
 * @param {OutputTabOptions} options
 */
function outputsTab(context, { field, hint, button, columns, create, apply = (item, key, value) => ({ ...item, [key]: value }) }) {
  const id = context.driver.id;
  /** @type {any[]} */
  let items = context.config[field];
  const nameOf = (/** @type {any} */ item) => (typeof item === "string" ? item : item.variable);
  const element = el("div.driver-tab");
  const table = new EditableTable(el("div.driver-table"), {
    filterable: false,
    columns: [
      { key: "variable", title: "Variable", width: 130, get: (row) => nameOf(row.item) },
      ...columns,
      { key: "remove", title: "Remove", width: 28, get: () => "", editor: "button", buttonText: "×" },
    ],
    onEdit: (row, column, value) => {
      const item = column.key === "remove" ? null : apply(row.item, column.key, value);
      return setConfig(id, field, replaced(items, row.index, item));
    },
  });
  const rows = () => items.map((item, index) => ({ key: `${nameOf(item)}#${index}`, index, item }));
  table.setRows(rows());
  element.append(
    tabHeader(hint, [
      pickButton(
        button,
        async () => (await context.variables()).outputs,
        () => items.map(nameOf),
        (name) => setConfig(id, field, [...items, create(name)]),
        "No output: put components inside the driver first",
      ),
    ]),
    /** @type {HTMLElement} */ (table.root.parentElement),
  );
  return {
    element,
    update: (/** @type {import("./common.js").TabContext} */ next) => {
      items = next.config[field];
      table.setRows(rows());
    },
  };
}

/** @param {import("./common.js").TabContext} context */
export function objectivesTab(context) {
  return outputsTab(context, {
    field: "objectives",
    hint: "The output to minimize (a cost, a mass) or maximize (a range, an efficiency). With several objectives, the algorithm (MNBI) finds the compromises between them: a Pareto front.",
    button: "Add objective",
    columns: [
      {
        key: "sense",
        title: "Sense",
        width: 90,
        get: (row) => row.item.sense ?? "minimize",
        editor: "select",
        options: ["minimize", "maximize"],
      },
    ],
    create: (name) => ({ variable: name, sense: "minimize" }),
  });
}

/** @param {import("./common.js").TabContext} context */
export function constraintsTab(context) {
  return outputsTab(context, {
    field: "constraints",
    hint: "The limits the design must respect. For example stress <= 250 keeps the stress at most 250, and mass == 10 (type eq) fixes it. Most algorithms handle inequalities more easily than equalities; a constraint is active at the optimum when it is at its limit.",
    button: "Add constraint",
    columns: [
      { key: "type", title: "Type", width: 64, get: (row) => row.item.type ?? "ineq", editor: "select", options: ["ineq", "eq"] },
      {
        key: "operator",
        title: "Operator",
        width: 64,
        get: (row) => (row.item.type === "eq" ? "==" : (row.item.operator ?? "<=")),
        editable: (row) => row.item.type !== "eq",
        editor: "select",
        options: ["<=", ">="],
      },
      {
        key: "value",
        title: "Value",
        width: 80,
        get: (row) => row.item.value_text ?? row.item.value ?? 0,
        editor: "text",
        parse: (text) => {
          const parsed = parseValue(text);
          if (parsed.value === null) {
            return { value: { number: 0, text: null }, error: null };
          }
          return typeof parsed.value === "number"
            ? { value: { number: parsed.value, text: text.trim() }, error: null }
            : { value: null, error: "Enter a number." };
        },
      },
    ],
    create: (name) => ({ variable: name, type: "ineq", operator: "<=", value: 0 }),
    apply: (item, key, value) =>
      key === "value" ? { ...item, value: value.number, value_text: value.text } : { ...item, [key]: value },
  });
}

/** @param {import("./common.js").TabContext} context */
export function observablesTab(context) {
  return outputsTab(context, {
    field: "observables",
    hint: "Outputs recorded at each iteration without being optimized.",
    button: "Add observable",
    columns: [],
    create: (name) => name,
  });
}

/** @param {import("./common.js").TabContext} context */
export function responsesTab(context) {
  return outputsTab(context, {
    field: "responses",
    hint: "The outputs computed for each sample. GEMSEO needs an objective: the first response plays that part.",
    button: "Add response",
    columns: [],
    create: (name) => name,
  });
}

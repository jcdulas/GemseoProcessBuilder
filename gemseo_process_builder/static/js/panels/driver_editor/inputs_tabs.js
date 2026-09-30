// @ts-check
// Tabs choosing the inputs a driver varies: design variables and parametric levels.
import { el } from "../../components/dom.js";
import { EditableTable } from "../../components/editable_table.js";
import { formatVector, parseVector } from "../../lib/driver_config.js";
import { parseValue } from "../../lib/table_model.js";
import { pickButton, replaced, setConfig, tabHeader } from "./common.js";

/**
 * The initial value of a new design variable: the default of its input.
 *
 * @param {import("./common.js").Variable} input
 */
export function newDesignVariable(input) {
  const values = Array.isArray(input.default) ? input.default : [input.default];
  const numeric = values.length === input.size && values.every((value) => typeof value === "number");
  return {
    variable: input.name,
    size: input.size,
    value: numeric ? values : [],
    type: input.dtype === "int" ? "integer" : "float",
  };
}

/**
 * A column editing a vector (bounds or initial value) of a design variable.
 *
 * @param {"lower" | "upper" | "value"} key
 * @param {string} title
 * @returns {import("../../components/editable_table.js").Column}
 */
function vectorColumn(key, title) {
  return {
    key,
    title,
    width: 90,
    get: (row) => formatVector(row.item[key], row.item.texts?.[key]),
    editor: "text",
    parse: (text, row) => {
      const parsed = parseVector(text, row.item.size);
      return { value: parsed, error: parsed.error };
    },
  };
}

/** @param {import("./common.js").TabContext} context */
export function designSpaceTab(context) {
  // With IDF, the optimizer also sets the coupling variables.
  const idf = context.driver.kind === "optimization" && context.config.formulation.name === "IDF";
  const candidates = (/** @type {import("./common.js").DriverVariables} */ variables) =>
    idf ? [...variables.inputs, ...variables.couplings] : variables.inputs;
  const id = context.driver.id;
  let items = context.config.design_space;
  const element = el("div.driver-tab");
  const table = new EditableTable(el("div.driver-table"), {
    filterable: false,
    columns: [
      { key: "variable", title: "Variable", width: 110, get: (row) => row.item.variable },
      { key: "size", title: "Size", width: 40, get: (row) => row.item.size },
      vectorColumn("lower", "Lower bound"),
      vectorColumn("upper", "Upper bound"),
      vectorColumn("value", "Initial value"),
      { key: "type", title: "Type", width: 64, get: (row) => row.item.type ?? "float", editor: "select", options: ["float", "integer"] },
      { key: "remove", title: "Remove", width: 28, get: () => "", editor: "button", buttonText: "×" },
    ],
    onEdit: (row, column, value) => {
      if (column.key === "remove") {
        return setConfig(id, "design_space", replaced(items, row.index, null));
      }
      if (column.key === "type") {
        return setConfig(id, "design_space", replaced(items, row.index, { ...row.item, type: value }));
      }
      const texts = { ...row.item.texts };
      if (value.text === null) {
        delete texts[column.key];
      } else {
        texts[column.key] = value.text;
      }
      const item = { ...row.item, [column.key]: value.values, texts };
      return setConfig(id, "design_space", replaced(items, row.index, item));
    },
  });
  const rows = () => items.map((item, index) => ({ key: item.variable, index, item }));
  table.setRows(rows());
  element.append(
    tabHeader(
      "Only the free inputs of the driver (computed by no discipline) can be design variables. " +
        "Type one value to fill a vector, or one value per element; leave a bound empty for no bound." +
        (context.driver.kind === "optimization"
          ? " Tips: an optimizer starts from the initial values; realistic bounds help every algorithm, and are needed by derivative-free and global ones."
          : ""),
      [
        pickButton(
          "Add design variable",
          async () => candidates(await context.variables()),
          () => items.map((item) => item.variable),
          async (name) => {
            const input = candidates(await context.variables()).find((candidate) => candidate.name === name);
            if (input) {
              setConfig(id, "design_space", [...items, newDesignVariable(input)]);
            }
          },
          "No free input: put components inside the driver first (their inputs computed by no other component can vary)",
        ),
      ],
    ),
    /** @type {HTMLElement} */ (table.root.parentElement),
  );
  return {
    element,
    update: (/** @type {import("./common.js").TabContext} */ next) => {
      items = next.config.design_space;
      table.setRows(rows());
    },
  };
}

/**
 * @param {string} text
 * @returns {{value: number[], error: string | null}}
 */
function parseList(text) {
  const values = text.split(/[\s,;]+/).filter(Boolean).map(Number);
  return values.some(Number.isNaN)
    ? { value: [], error: "Enter numbers separated by commas." }
    : { value: values, error: null };
}

/** @param {import("./common.js").TabContext} context */
export function levelsTab(context) {
  const id = context.driver.id;
  let items = context.config.levels;
  const element = el("div.driver-tab");
  /**
   * @param {string} key
   * @param {string} title
   * @returns {import("../../components/editable_table.js").Column}
   */
  const numberColumn = (key, title) => ({
    key,
    title,
    width: 70,
    get: (row) => row.item[key] ?? "",
    editable: (row) => row.item.mode !== "list",
    editor: "text",
    parse: (text) => {
      const parsed = parseValue(text);
      return typeof parsed.value === "number" ? parsed : { value: null, error: "Enter a number." };
    },
  });
  const table = new EditableTable(el("div.driver-table"), {
    filterable: false,
    columns: [
      { key: "variable", title: "Variable", width: 110, get: (row) => row.item.variable },
      { key: "mode", title: "Levels", width: 80, get: (row) => row.item.mode ?? "linspace", editor: "select", options: ["linspace", "list"] },
      numberColumn("lower", "From"),
      numberColumn("upper", "To"),
      {
        key: "count",
        title: "Count",
        width: 50,
        get: (row) => row.item.count ?? 3,
        editable: (row) => row.item.mode !== "list",
        editor: "text",
        parse: (text) => {
          const count = Number(text);
          return Number.isInteger(count) && count > 0 ? { value: count, error: null } : { value: null, error: "Enter a positive whole number." };
        },
      },
      {
        key: "values",
        title: "Values",
        width: 120,
        get: (row) => (row.item.values ?? []).join(", "),
        editable: (row) => row.item.mode === "list",
        editor: "text",
        parse: (text) => parseList(text),
      },
      { key: "remove", title: "Remove", width: 28, get: () => "", editor: "button", buttonText: "×" },
    ],
    onEdit: (row, column, value) => {
      const item = column.key === "remove" ? null : { ...row.item, [column.key]: value };
      return setConfig(id, "levels", replaced(items, row.index, item));
    },
  });
  const rows = () => items.map((item, index) => ({ key: item.variable, index, item }));
  table.setRows(rows());
  element.append(
    tabHeader("Each variable takes evenly spaced values between two bounds, or a list of values; every combination is run.", [
      pickButton(
        "Add variable",
        async () => (await context.variables()).inputs,
        () => items.map((item) => item.variable),
        (name) => setConfig(id, "levels", [...items, { variable: name, mode: "linspace", lower: 0, upper: 1, count: 3 }]),
        "No free input: put components inside the driver first (their inputs computed by no other component can vary)",
      ),
    ]),
    /** @type {HTMLElement} */ (table.root.parentElement),
  );
  return {
    element,
    update: (/** @type {import("./common.js").TabContext} */ next) => {
      items = next.config.levels;
      table.setRows(rows());
    },
  };
}

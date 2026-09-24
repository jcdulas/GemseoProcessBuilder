// @ts-check
// Built-in node types and the nodes created from catalog entries.

/**
 * @typedef {object} LibraryItem
 * @property {string} id
 * @property {string} label
 * @property {string} group
 * @property {string} description
 * @property {object} node - The node given to the addNode command.
 */

/** @type {LibraryItem[]} */
export const BUILTIN_ITEMS = [
  {
    id: "builtin.analytic",
    label: "Analytic",
    group: "Components",
    description: "Formulas typed in the inspector, like y = x**2.",
    node: { type: "component", kind: "analytic", name: "Analytic", config: { expressions: {} } },
  },
  {
    id: "builtin.python_function",
    label: "Python function",
    group: "Components",
    description: "A Python function whose arguments are inputs and returned names outputs.",
    node: { type: "component", kind: "python_function", name: "Function", config: {} },
  },
  {
    id: "builtin.python_class",
    label: "Python class",
    group: "Components",
    description: "A GEMSEO Discipline class from a Python module.",
    node: { type: "component", kind: "python_class", name: "Discipline", config: {} },
  },
  {
    id: "builtin.executable",
    label: "Executable wrapper",
    group: "Components",
    description: "An external program driven through input and output files.",
    node: { type: "component", kind: "executable", name: "Executable", config: {} },
  },
  {
    id: "builtin.surrogate",
    label: "Surrogate",
    group: "Components",
    description: "A surrogate model trained on a DOE of the project.",
    node: { type: "component", kind: "surrogate", name: "Surrogate", config: {} },
  },
  {
    id: "builtin.assembly",
    label: "Assembly",
    group: "Containers",
    description: "A group of nodes run as a chain, in parallel or with an MDA.",
    node: { type: "assembly", name: "Assembly" },
  },
  {
    id: "builtin.mda",
    label: "MDA",
    group: "Drivers",
    description: "Solves the couplings of its children once.",
    node: { type: "driver", kind: "mda", name: "MDA" },
  },
  {
    id: "builtin.doe",
    label: "DOE",
    group: "Drivers",
    description: "Evaluates its children on a design of experiments.",
    node: { type: "driver", kind: "doe", name: "DOE" },
  },
  {
    id: "builtin.optimization",
    label: "Optimization",
    group: "Drivers",
    description: "Optimizes its children with an MDO formulation.",
    node: { type: "driver", kind: "optimization", name: "Optimizer" },
  },
  {
    id: "builtin.parametric",
    label: "Parametric study",
    group: "Drivers",
    description: "Sweeps one or more variables over levels.",
    node: { type: "driver", kind: "parametric", name: "Parametric" },
  },
];

/**
 * A valid node name made from any text.
 *
 * @param {string} text
 * @returns {string}
 */
export function toNodeName(text) {
  const cleaned = text.replace(/[^A-Za-z0-9_]/g, "_").replace(/^[^A-Za-z]+/, "");
  return cleaned || "Component";
}

/**
 * The node created from a catalog entry.
 *
 * @param {{kind: string, name: string, module_path: string, attribute: string}} entry
 * @returns {object}
 */
export function nodeFromEntry(entry) {
  const name = toNodeName(entry.name);
  if (entry.kind === "python_class") {
    return {
      type: "component",
      kind: "python_class",
      name,
      config: { module_path: entry.module_path, class: entry.attribute, init_args: {} },
    };
  }
  if (entry.kind === "python_function") {
    return {
      type: "component",
      kind: "python_function",
      name,
      config: { module_path: entry.module_path, function: entry.attribute },
    };
  }
  return { type: "component", kind: "executable", name, config: { descriptor_path: entry.module_path } };
}

/**
 * Keep the library items matching a search text.
 *
 * @template {{label: string, description?: string}} T
 * @param {T[]} items
 * @param {string} text
 * @returns {T[]}
 */
export function searchItems(items, text) {
  const needle = text.trim().toLowerCase();
  if (!needle) {
    return items;
  }
  return items.filter(
    (item) => item.label.toLowerCase().includes(needle) || (item.description ?? "").toLowerCase().includes(needle),
  );
}

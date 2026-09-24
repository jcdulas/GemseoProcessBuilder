// @ts-check
// Pure helpers of the driver editor: tabs, defaults, vectors, roles.

/** @typedef {{id: string, label: string}} Tab */

/** @type {Record<string, Tab[]>} */
const TABS = {
  optimization: [
    { id: "design_space", label: "Design variables" },
    { id: "objectives", label: "Objectives" },
    { id: "constraints", label: "Constraints" },
    { id: "observables", label: "Observables" },
    { id: "algorithm", label: "Algorithm" },
    { id: "formulation", label: "Formulation" },
    { id: "execution", label: "Execution" },
  ],
  doe: [
    { id: "design_space", label: "Design variables" },
    { id: "responses", label: "Responses" },
    { id: "algorithm", label: "Algorithm" },
    { id: "formulation", label: "Formulation" },
    { id: "execution", label: "Execution" },
  ],
  parametric: [
    { id: "levels", label: "Levels" },
    { id: "responses", label: "Responses" },
    { id: "execution", label: "Execution" },
  ],
  mda: [{ id: "mda_settings", label: "MDA settings" }],
};

/** The algorithm used while none is chosen (same as ``core/drivers.py``). */
export const DEFAULT_ALGORITHMS = { mda: "MDAChain", doe: "LHS", optimization: "SLSQP", parametric: "CustomDOE" };

/** The formulation used while none is chosen. */
export const DEFAULT_FORMULATIONS = { doe: "DisciplinaryOpt", optimization: "MDF", parametric: "DisciplinaryOpt" };

/**
 * The tabs of the editor of a driver kind.
 *
 * @param {string} kind
 * @returns {Tab[]}
 */
export function tabsFor(kind) {
  return TABS[kind] ?? [];
}

/**
 * A driver configuration with every field present.
 *
 * @param {Record<string, any> | undefined} config
 */
export function withDefaults(config) {
  return {
    design_space: [],
    objectives: [],
    constraints: [],
    observables: [],
    responses: [],
    algorithm: { name: "", settings: {} },
    formulation: { name: "", settings: {} },
    mda_settings: {},
    levels: [],
    execution: { n_processes: 1, save_history: true, working_directory: "" },
    ...(config ?? {}),
  };
}

/**
 * Read a vector typed by the user: one value per element, or a single value
 * for every element. Empty means unbounded (or no initial value).
 *
 * @param {string} text
 * @param {number} size
 * @returns {{values: number[], text: string | null, error: string | null}}
 */
export function parseVector(text, size) {
  const parts = text.split(/[\s,;]+/).filter(Boolean);
  if (!parts.length) {
    return { values: [], text: null, error: null };
  }
  const numbers = parts.map(Number);
  if (numbers.some(Number.isNaN)) {
    return { values: [], text: null, error: "Enter numbers separated by commas." };
  }
  if (parts.length === 1) {
    return { values: Array(size).fill(numbers[0]), text: parts[0], error: null };
  }
  if (parts.length !== size) {
    return { values: [], text: null, error: `Enter one value or ${size} values.` };
  }
  return { values: numbers, text: null, error: null };
}

/**
 * The text of a vector: as typed when one value fills it, else its values.
 *
 * @param {(number | null)[]} values
 * @param {string | undefined} text
 */
export function formatVector(values, text) {
  if (!values?.length) {
    return "";
  }
  if (text !== undefined) {
    return text;
  }
  return values.every((value) => value === values[0]) ? String(values[0]) : values.join(", ");
}

/**
 * The items of a variable picker: the candidates not used yet come first.
 *
 * @param {{name: string, size: number}[]} candidates
 * @param {string[]} used
 * @returns {{name: string, label: string, enabled: boolean}[]}
 */
export function pickerItems(candidates, used) {
  const taken = new Set(used);
  return candidates
    .map((candidate) => ({
      name: candidate.name,
      label: candidate.size > 1 ? `${candidate.name} (${candidate.size})` : candidate.name,
      enabled: !taken.has(candidate.name),
    }))
    .sort((a, b) => Number(b.enabled) - Number(a.enabled) || a.name.localeCompare(b.name));
}

/** Short badges shown in the tree and the Variables table. */
const ROLE_BADGES = {
  "design variable": "DV",
  objective: "OBJ",
  constraint: "CON",
  observable: "OBS",
  response: "RES",
};

/**
 * @param {string[]} roles
 * @returns {string}
 */
export function roleBadges(roles) {
  return roles.map((role) => ROLE_BADGES[/** @type {keyof ROLE_BADGES} */ (role)] ?? role).join(" ");
}

/**
 * The roles a port can take in a driver of a kind, as menu entries.
 *
 * @param {string} kind
 * @param {"in" | "out"} direction
 * @returns {{role: string, label: string}[]}
 */
export function roleChoices(kind, direction) {
  if (direction === "in") {
    if (kind === "optimization" || kind === "doe") {
      return [{ role: "design_variable", label: "Set as design variable" }];
    }
    return kind === "parametric" ? [{ role: "level", label: "Vary in the parametric study" }] : [];
  }
  if (kind === "optimization") {
    return [
      { role: "objective", label: "Set as objective" },
      { role: "constraint", label: "Set as constraint" },
      { role: "observable", label: "Add as observable" },
    ];
  }
  return kind === "doe" || kind === "parametric" ? [{ role: "response", label: "Add as response" }] : [];
}

/**
 * The closest driver containing a node, from the ids of its ancestors.
 *
 * @param {string[]} path - Ids from the root to the node.
 * @param {(id: string) => any} nodeOf
 * @returns {any | null}
 */
export function enclosingDriver(path, nodeOf) {
  for (let index = path.length - 2; index >= 0; index -= 1) {
    const node = nodeOf(path[index]);
    if (node?.type === "driver") {
      return node;
    }
  }
  return null;
}

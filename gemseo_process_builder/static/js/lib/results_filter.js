// @ts-check
// The variables and responses the Results views show. A run can have hundreds
// of thousands of design variables and many responses: the views show those
// that matter, ranked by the worker (`results.ranking`) by sensitivity,
// gradient or active set (SPEC § 12.2). Pure: no DOM.

/**
 * @typedef {object} FilterState
 * @property {"all" | "sensitivity" | "gradient" | "active"} mode - How the design variables are chosen.
 * @property {string} response - The response they are ranked for; the objective when empty.
 * @property {number} count - The number of ranked design variables kept.
 * @property {"all" | "active"} constraints - All the constraints, or the active and violated ones.
 */

/**
 * @typedef {object} Ranking - The result of `results.ranking`.
 * @property {string} method
 * @property {string} response
 * @property {number} evaluation - The best evaluation, where gradients and bounds are read.
 * @property {string} note
 * @property {{name: string, score: number, bound: "lower" | "upper" | null}[]} inputs
 * @property {{name: string, role: string, value: number | null, status: "violated" | "active" | "satisfied" | null}[]} responses
 * @property {number} total_inputs
 * @property {number} total_responses
 * @property {number} at_bounds
 */

/**
 * @typedef {object} FilterResult
 * @property {string[]} inputs - The design variables shown, the most important first.
 * @property {string[]} responses - The responses shown: objective, outputs, then constraints.
 * @property {number} totalInputs
 * @property {number} totalResponses
 * @property {Map<string, number>} scores - The score of each ranked design variable.
 * @property {Map<string, string>} bounds - "lower" or "upper" for the design variables at a bound.
 * @property {Map<string, string>} statuses - violated, active or satisfied, by constraint.
 */

/** @type {FilterState} */
export const DEFAULT_FILTER = { mode: "all", response: "", count: 10, constraints: "all" };

export const MODES = [
  { value: "all", label: "All" },
  { value: "sensitivity", label: "Most sensitive" },
  { value: "gradient", label: "Largest gradients" },
  { value: "active", label: "Active set (at bounds)" },
];

const RESPONSE_ORDER = ["objective", "output", "observable", "constraint"];

/** The number of responses the ranking returns at most. */
export const MAX_RESPONSES = 500;

/**
 * Whether the filter needs the ranking of the worker.
 *
 * @param {FilterState} state
 */
export function needsRanking(state) {
  return state.mode !== "all" || state.constraints === "active";
}

/**
 * The parameters of `results.ranking` for a filter.
 *
 * @param {FilterState} state
 */
export function rankingQuery(state) {
  return {
    method: state.mode === "all" ? "active" : state.mode,
    response: state.mode === "sensitivity" || state.mode === "gradient" ? state.response : "",
    limit: state.mode === "all" ? 0 : Math.max(1, Math.round(state.count)),
    active_only: state.constraints === "active",
    response_limit: MAX_RESPONSES,
  };
}

/**
 * The variables and responses a filter keeps.
 *
 * @param {{name: string, role: string}[]} columns - The columns of the run.
 * @param {FilterState} state
 * @param {Ranking | null} ranking - Needed when `needsRanking(state)`.
 * @returns {FilterResult}
 */
export function applyFilter(columns, state, ranking) {
  const known = new Set(columns.map((column) => column.name));
  const designs = columns.filter((column) => column.role === "design variable").map((column) => column.name);
  const responseColumns = columns.filter((column) => RESPONSE_ORDER.includes(column.role) && column.name !== "feasible");
  /** @type {Map<string, number>} */
  const scores = new Map();
  /** @type {Map<string, string>} */
  const bounds = new Map();
  /** @type {Map<string, string>} */
  const statuses = new Map();
  for (const item of ranking?.inputs ?? []) {
    scores.set(item.name, item.score);
    if (item.bound) {
      bounds.set(item.name, item.bound);
    }
  }
  for (const item of ranking?.responses ?? []) {
    if (item.status) {
      statuses.set(item.name, item.status);
    }
  }

  let inputs = designs;
  if (state.mode !== "all" && ranking) {
    const ranked = ranking.inputs.filter((item) => known.has(item.name));
    inputs = (state.mode === "active" ? ranked.filter((item) => item.bound) : ranked)
      .slice(0, Math.max(1, Math.round(state.count)))
      .map((item) => item.name);
  }

  let kept = responseColumns;
  if (state.constraints === "active" && ranking) {
    kept = responseColumns.filter((column) => column.role !== "constraint" || ["violated", "active"].includes(statuses.get(column.name) ?? ""));
  }
  // The objective first; constraints in the ranking order (most violated first).
  const order = new Map((ranking?.responses ?? []).map((item, index) => [item.name, index]));
  const responses = [...kept]
    .sort(
      (a, b) =>
        RESPONSE_ORDER.indexOf(a.role) - RESPONSE_ORDER.indexOf(b.role) ||
        (order.get(a.name) ?? Infinity) - (order.get(b.name) ?? Infinity),
    )
    .map((column) => column.name);
  return {
    inputs,
    responses,
    totalInputs: designs.length,
    totalResponses: responseColumns.length,
    scores,
    bounds,
    statuses,
  };
}

/** "1,234" */
function count(/** @type {number} */ value) {
  return value.toLocaleString("en-US");
}

/**
 * What the filter shows, in one sentence.
 *
 * @param {FilterState} state
 * @param {FilterResult} result
 * @param {Ranking | null} ranking
 */
export function describeFilter(state, result, ranking) {
  const parts = [];
  const variables = `${count(result.inputs.length)} of ${count(result.totalInputs)} design variables`;
  if (state.mode === "sensitivity" && ranking) {
    parts.push(`${variables}, most correlated with ${ranking.response}`);
  } else if (state.mode === "gradient" && ranking) {
    parts.push(`${variables}, largest gradients of ${ranking.response} × range`);
  } else if (state.mode === "active" && ranking) {
    parts.push(`${variables} at a bound (${count(ranking.at_bounds)} in all)`);
  } else {
    parts.push(`${count(result.totalInputs)} design variables`);
  }
  const constraints = [...result.statuses.values()];
  const violated = constraints.filter((status) => status === "violated").length;
  const active = constraints.filter((status) => status === "active").length;
  if (ranking && (active || violated || state.constraints === "active")) {
    parts.push(`${active} active and ${violated} violated constraints`);
  }
  if (ranking) {
    parts.push(`at the best evaluation (${ranking.evaluation})`);
  }
  return parts.join(" · ") + (ranking?.note ? `. ${ranking.note}` : "");
}

/**
 * The names to show among a list, with how many are left out.
 *
 * @param {string[]} names
 * @param {number} limit
 */
export function firstOf(names, limit) {
  return { shown: names.slice(0, limit), hidden: Math.max(0, names.length - limit) };
}

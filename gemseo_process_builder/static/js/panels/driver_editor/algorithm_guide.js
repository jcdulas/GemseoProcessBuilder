// @ts-check
// What the chosen algorithm (or formulation) does, the algorithm suggested for
// the problem of an optimization, and all the algorithms side by side.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { openModal } from "../../components/modal.js";
import { guideOf, sortedByGuide, suggestAlgorithm, worstOrigin } from "../../lib/algorithm_guide.js";

/** @typedef {"optimization" | "doe" | "formulation"} GuideKind */

/** The capabilities GEMSEO gives, as badges: [key, shown when true, shown when false]. */
const BADGES = [
  ["require_gradient", "Uses gradients", "Derivative-free"],
  ["handle_inequality_constraints", "Inequality constraints", null],
  ["handle_equality_constraints", "Equality constraints", null],
  ["handle_integer_variables", "Integers", null],
  ["handle_multiobjective", "Several objectives", null],
];

/**
 * The badges of the capabilities of an optimization algorithm.
 *
 * @param {Record<string, boolean>} capabilities
 */
function badges(capabilities) {
  return BADGES.flatMap(([key, yes, no]) => {
    const text = capabilities[/** @type {string} */ (key)] ? yes : no;
    return text ? [el("span.guide-badge", { text })] : [];
  });
}

/**
 * The guide of an algorithm: what it does, when to use it, its cost.
 *
 * @param {GuideKind} kind
 * @param {any} item - An item of `driver.algorithms`.
 */
export function guideCard(kind, item) {
  const guide = guideOf(kind, item.name);
  const reasons = item.reasons ?? [];
  return el("div.guide-card", {}, [
    el("div.guide-title", {}, [
      el("strong", { text: item.name }),
      guide ? el("span.guide-family", { text: guide.family }) : null,
      item.library && item.library !== "GEMSEO" ? el("span.form-hint", { text: item.library }) : null,
    ]),
    kind === "optimization" ? el("div.guide-badges", {}, badges(item.capabilities ?? {})) : null,
    el("p", { text: guide?.summary ?? item.description ?? "" }),
    guide ? el("p", {}, [el("strong", { text: "When: " }), guide.use]) : null,
    guide ? el("p", {}, [el("strong", { text: "Cost: " }), guide.cost]) : null,
    reasons.length ? el("p.form-error", { text: `It cannot solve this problem: ${reasons.join(", ")}.` }) : null,
  ]);
}

/**
 * The ids of the components under a node, at any depth.
 *
 * @param {string} id
 * @returns {string[]}
 */
function componentsUnder(id) {
  return app.store.children(id).flatMap((child) => (child.type === "component" ? [child.id] : componentsUnder(child.id)));
}

/**
 * The problem of an optimization, as the suggestion needs it.
 *
 * @param {any} driver
 * @param {ReturnType<typeof import("../../lib/driver_config.js").withDefaults>} config
 * @returns {import("../../lib/algorithm_guide.js").Problem}
 */
export function problemOf(driver, config) {
  return {
    variables: config.design_space.reduce((sum, item) => sum + (item.size ?? 1), 0),
    inequalities: config.constraints.filter((item) => (item.type ?? "ineq") === "ineq").length,
    equalities: config.constraints.filter((item) => item.type === "eq").length,
    objectives: config.objectives.length,
    integers: config.design_space.some((item) => item.type === "integer"),
    derivatives: worstOrigin(componentsUnder(driver.id).map((id) => app.derivatives.of(id).origin)),
  };
}

/**
 * The algorithm suggested for an optimization, and why; `null` without a
 * design variable or an objective.
 *
 * @param {any} driver
 * @param {ReturnType<typeof import("../../lib/driver_config.js").withDefaults>} config
 * @param {any[]} items - The items of `driver.algorithms`.
 */
export function suggested(driver, config, items) {
  if (!config.design_space.length || !config.objectives.length) {
    return null;
  }
  const available = new Set(items.filter((item) => !item.reasons?.length).map((item) => item.name));
  return suggestAlgorithm(problemOf(driver, config), available);
}

/**
 * The algorithm suggested for an optimization, with a button choosing it.
 *
 * @param {any} driver
 * @param {ReturnType<typeof import("../../lib/driver_config.js").withDefaults>} config
 * @param {any[]} items - The items of `driver.algorithms`.
 * @param {string} current
 * @param {(name: string) => void} choose
 */
export function suggestion(driver, config, items, current, choose) {
  if (!config.design_space.length || !config.objectives.length) {
    return el("p.form-hint", { text: "Choose the design variables and the objective: an algorithm will be suggested for the problem." });
  }
  const found = suggested(driver, config, items);
  if (!found) {
    return null;
  }
  const why = found.reasons.join("; ");
  if (found.name === current) {
    return el("div.guide-suggestion.agreed", { text: `✓ ${current} suits this problem: ${why}.` });
  }
  return el("div.guide-suggestion", {}, [
    el("span", {}, [`Suggested for this problem: `, el("strong", { text: found.name }), ` (${why}).`]),
    el("button.button.bordered.small", { text: `Use ${found.name}`, onClick: () => choose(found.name) }),
  ]);
}

/**
 * Every algorithm side by side, by family; a row chooses its algorithm.
 *
 * @param {GuideKind} kind
 * @param {any[]} items
 * @param {string} current
 * @param {(name: string) => void} choose
 * @param {string} [suggestedName] - Marked in the table.
 */
export function openComparison(kind, items, current, choose, suggestedName = "") {
  const families = new Map();
  for (const item of sortedByGuide(kind, items)) {
    const family = guideOf(kind, item.name)?.family ?? "Other";
    families.set(family, [...(families.get(family) ?? []), item]);
  }
  /** @type {() => void} */
  let close = () => {};
  const rows = [...families].flatMap(([family, members]) => [
    el("tr.guide-family-row", {}, [el("th", { colspan: "4", text: family })]),
    ...members.map((/** @type {any} */ item) => {
      const guide = guideOf(kind, item.name);
      const blocked = item.reasons?.length > 0;
      return el(`tr${item.name === current ? ".current" : ""}${blocked ? ".blocked" : ""}`, {}, [
        el("td", {}, [
          el("strong", { text: item.name }),
          item.name === suggestedName ? el("div.guide-family", { text: "Suggested" }) : null,
        ]),
        el("td", {}, [guide?.summary ?? item.description ?? "", guide ? el("div.form-hint", { text: guide.use }) : null]),
        el("td", {}, kind === "optimization" ? badges(item.capabilities ?? {}) : [guide?.cost ?? ""]),
        el("td", {}, [
          blocked
            ? el("span.form-hint", { text: item.reasons.join(", ") })
            : item.name === current
              ? el("span.form-hint", { text: "Chosen" })
              : el("button.button.bordered.small", {
                  text: "Use",
                  onClick: () => {
                    choose(item.name);
                    close();
                  },
                }),
        ]),
      ]);
    }),
  ]);
  const title = kind === "optimization" ? "Optimization algorithms" : kind === "doe" ? "Sampling methods" : "Formulations";
  close = openModal({
    title,
    body: el("div.guide-compare", {}, [el("table.guide-table", {}, rows)]),
  });
}

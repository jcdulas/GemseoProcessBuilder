// @ts-check
// The steps to set up a driver, shown at the top of its editor: what is done,
// what is missing and where to do it. Pure: no DOM.

/**
 * @typedef {object} Step
 * @property {string} id - "children", or the tab that completes the step.
 * @property {string} label
 * @property {string} hint - How to do it.
 * @property {boolean} done
 * @property {boolean} optional
 */

const WHAT = {
  doe: "the components to evaluate",
  optimization: "the components to optimize",
  parametric: "the components to study",
  mda: "the coupled components to solve",
};

/**
 * The steps of a driver kind, with their state.
 *
 * @param {string} kind - doe, optimization, parametric or mda.
 * @param {string} name - The name of the driver, as the user sees it.
 * @param {ReturnType<typeof import("./driver_config.js").withDefaults>} config
 * @param {number} children - The number of nodes inside the driver.
 * @param {string} defaultAlgorithm - The algorithm used while none is chosen.
 * @returns {{steps: Step[], ready: boolean}}
 */
export function driverSteps(kind, name, config, children, defaultAlgorithm) {
  /** @type {Step[]} */
  const steps = [
    {
      id: "children",
      label: `Put ${WHAT[/** @type {keyof WHAT} */ (kind)] ?? "components"} inside ${name}`,
      hint: `Draw a link from the card of ${name} to a component, or open ${name} and add components from the Library.`,
      done: children > 0,
      optional: false,
    },
  ];
  if (kind === "doe" || kind === "optimization") {
    steps.push({
      id: "design_space",
      label: kind === "doe" ? "Choose the variables to sample, with their bounds" : "Choose the design variables, with their bounds",
      hint: "Pick them among the inputs no component computes; then type their lower and upper bounds.",
      done: config.design_space.length > 0,
      optional: false,
    });
  }
  if (kind === "parametric") {
    steps.push({
      id: "levels",
      label: "Choose the variables to vary, with their values",
      hint: "Pick them among the inputs no component computes; then give their range or their list of values.",
      done: config.levels.length > 0,
      optional: false,
    });
  }
  if (kind === "optimization") {
    steps.push({
      id: "objectives",
      label: "Choose the objective to minimize or maximize",
      hint: "Pick an output of the components; constraints are optional, in the Constraints tab.",
      done: config.objectives.length > 0,
      optional: false,
    });
  }
  if (kind === "optimization") {
    const count = config.constraints.length;
    steps.push({
      id: "constraints",
      label: count ? `Constraints: ${count}` : "Add constraints, if the design must respect limits",
      hint: "Keep outputs below, above or at a value, like stress <= 250.",
      done: true,
      optional: true,
    });
    steps.push({
      id: "formulation",
      label: `Check the formulation: ${config.formulation.name || "MDF"}`,
      hint: "How the couplings between the components are solved; MDF suits most problems.",
      done: true,
      optional: true,
    });
  }
  if (kind === "doe" || kind === "parametric") {
    steps.push({
      id: "responses",
      label: "Choose the responses to record",
      hint: "Pick the outputs to look at in the results; the first one is the main response.",
      done: config.responses.length > 0,
      optional: false,
    });
  }
  if (kind === "doe" || kind === "optimization") {
    const algorithm = config.algorithm.name || defaultAlgorithm;
    const samples = config.algorithm.settings?.n_samples;
    steps.push({
      id: "algorithm",
      label:
        kind === "doe"
          ? `Check the sampling: ${algorithm}${samples ? `, ${samples} samples` : ""}`
          : `Check the algorithm: ${algorithm}`,
      hint:
        kind === "doe"
          ? "Change the method or the number of samples in the Algorithm tab."
          : "The Algorithm tab suggests one for the problem and explains each of them.",
      done: true,
      optional: true,
    });
  }
  return { steps, ready: steps.every((step) => step.done) };
}

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  OPTIMIZATION_GUIDES,
  guideOf,
  sortedByGuide,
  suggestAlgorithm,
  worstOrigin,
} from "../../gemseo_process_builder/static/js/lib/algorithm_guide.js";
import { driverSteps } from "../../gemseo_process_builder/static/js/lib/driver_checklist.js";
import { withDefaults } from "../../gemseo_process_builder/static/js/lib/driver_config.js";
import { complete, completions, formulaSymbols, wordAt } from "../../gemseo_process_builder/static/js/lib/formula_help.js";

test("a new DOE: every step is missing, the sampling is only to check", () => {
  const { steps, ready } = driverSteps("doe", "DOE", withDefaults({}), 0, "LHS");
  assert.equal(ready, false);
  assert.deepEqual(
    steps.map((step) => [step.id, step.done, step.optional]),
    [
      ["children", false, false],
      ["design_space", false, false],
      ["responses", false, false],
      ["algorithm", true, true],
    ],
  );
  assert.equal(steps[0].label, "Put the components to evaluate inside DOE");
  assert.equal(steps[3].label, "Check the sampling: LHS");
});

test("a DOE set up is ready, with its number of samples", () => {
  const config = withDefaults({
    design_space: [{ variable: "x" }],
    responses: ["f"],
    algorithm: { name: "OT_SOBOL", settings: { n_samples: 50 } },
  });
  const { steps, ready } = driverSteps("doe", "Study", config, 2, "LHS");
  assert.equal(ready, true);
  assert.equal(steps[3].label, "Check the sampling: OT_SOBOL, 50 samples");
});

test("an optimization needs an objective; a parametric study levels; an MDA components", () => {
  const optimization = driverSteps("optimization", "Optimizer", withDefaults({ design_space: [{ variable: "x" }] }), 1, "SLSQP");
  assert.deepEqual(
    optimization.steps.filter((step) => !step.done).map((step) => step.id),
    ["objectives"],
  );
  assert.deepEqual(
    optimization.steps.filter((step) => step.optional).map((step) => step.label),
    ["Add constraints, if the design must respect limits", "Check the formulation: MDF", "Check the algorithm: SLSQP"],
  );
  const parametric = driverSteps("parametric", "Study", withDefaults({}), 1, "CustomDOE");
  assert.deepEqual(
    parametric.steps.map((step) => step.id),
    ["children", "levels", "responses"],
  );
  const mda = driverSteps("mda", "MDA", withDefaults({}), 2, "MDAChain");
  assert.deepEqual(mda, { steps: [mda.steps[0]], ready: true });
});

test("the inputs and outputs of formulas, and the names SymPy misreads", () => {
  const symbols = formulaSymbols({ area: "pi*radius**2", y: "sqrt(x) + 1e5*gamma + E" });
  assert.deepEqual(symbols, {
    inputs: ["radius", "x"],
    outputs: ["area", "y"],
    functions: ["sqrt"],
    reserved: ["E", "gamma"],
  });
  // An output used in another formula is not an input of the component.
  assert.deepEqual(formulaSymbols({ a: "x", b: "a + 1" }).inputs, ["x"]);
  assert.deepEqual(formulaSymbols({ S: "x" }).reserved, ["S"]);
});

test("the word being typed, its completions and their insertion", () => {
  assert.deepEqual(wordAt("y = 2*spe", 9), { word: "spe", start: 6, end: 9 });
  assert.equal(wordAt("y = 2*", 6), null);
  assert.equal(wordAt("y = 12", 6), null); // A number, not a name.
  const found = completions("s", ["span", "x"]);
  assert.deepEqual(
    found.map((item) => item.name).slice(0, 4),
    ["span", "sqrt", "sin", "sinh"],
  );
  assert.deepEqual(completions("sqrt", []), []); // Already complete.
  assert.deepEqual(complete("y = sq", { start: 4, end: 6 }, "sqrt()"), { text: "y = sqrt()", caret: 9 });
  assert.deepEqual(complete("y = sp + 1", { start: 4, end: 6 }, "span"), { text: "y = span + 1", caret: 8 });
});

test("every algorithm, sampling method and formulation of GEMSEO has a guide", () => {
  const optimization = [
    "Augmented_Lagrangian_order_0", "Augmented_Lagrangian_order_1", "MNBI", "MultiStart", "NLOPT_MMA", "NLOPT_COBYLA",
    "NLOPT_SLSQP", "NLOPT_BOBYQA", "NLOPT_BFGS", "NLOPT_NEWUOA", "DUAL_ANNEALING", "SHGO", "DIFFERENTIAL_EVOLUTION",
    "INTERIOR_POINT", "DUAL_SIMPLEX", "Scipy_MILP", "SLSQP", "L-BFGS-B", "TNC", "NELDER-MEAD", "COBYQA",
  ];
  const doe = ["CustomDOE", "DiagonalDOE", "MorrisDOE", "OATDOE", "Halton", "LHS", "MC", "PoissonDisk", "Sobol"];
  const formulations = ["BiLevel", "BiLevelBCD", "DisciplinaryOpt", "IDF", "MDF"];
  for (const [kind, names] of /** @type {const} */ ([["optimization", optimization], ["doe", doe], ["formulation", formulations]])) {
    for (const name of names) {
      const guide = guideOf(kind, name);
      assert.ok(guide && guide.family && guide.summary && guide.use && guide.cost, `${kind} ${name}`);
    }
  }
  assert.equal(guideOf("doe", "Unknown"), null);
});

test("the algorithm suggested for a problem", () => {
  const all = new Set(Object.keys(OPTIMIZATION_GUIDES));
  /** @type {import("../../gemseo_process_builder/static/js/lib/algorithm_guide.js").Problem} */
  const base = { variables: 4, inequalities: 2, equalities: 0, objectives: 1, integers: false, derivatives: "exact" };
  const suggest = (/** @type {any} */ change) => suggestAlgorithm({ ...base, ...change }, all)?.name;
  assert.deepEqual(suggestAlgorithm(base, all), {
    name: "SLSQP",
    reasons: ["the components compute their derivatives", "4 design variables and inequality constraints"],
  });
  assert.equal(suggest({ variables: 5000 }), "NLOPT_MMA");
  assert.equal(suggest({ variables: 5000, inequalities: 0 }), "L-BFGS-B");
  assert.equal(suggest({ equalities: 1, variables: 5000 }), "SLSQP");
  assert.equal(suggest({ derivatives: "missing" }), "COBYQA");
  assert.equal(suggest({ derivatives: "approximated", variables: 10 }), "SLSQP");
  assert.equal(suggest({ derivatives: "approximated", variables: 100 }), "NLOPT_COBYLA");
  assert.equal(suggest({ derivatives: "missing", inequalities: 0 }), "NLOPT_BOBYQA");
  assert.equal(suggest({ objectives: 2 }), "MNBI");
  assert.equal(suggest({ integers: true }), "DIFFERENTIAL_EVOLUTION");
  // Not offered when it cannot be chosen.
  assert.equal(suggestAlgorithm(base, new Set(["COBYQA"])), null);
  assert.equal(worstOrigin(["exact", "approximated", ""]), "approximated");
  assert.equal(worstOrigin([]), "");
});

test("algorithms sorted by family, the usual ones first", () => {
  const items = ["MNBI", "COBYQA", "Unknown", "SLSQP", "NLOPT_MMA"].map((name) => ({ name }));
  assert.deepEqual(
    sortedByGuide("optimization", items).map((item) => item.name),
    ["SLSQP", "NLOPT_MMA", "COBYQA", "MNBI", "Unknown"],
  );
});

// @ts-check
// What each algorithm and formulation does, when to use it and what it costs,
// and the optimization algorithm suggested for a problem. GEMSEO describes its
// algorithms in a few words ("Dual annealing"): this guide says more. Pure: no DOM.

/**
 * @typedef {object} Guide
 * @property {string} family - Like "Gradient-based, local".
 * @property {string} summary - What it does.
 * @property {string} use - When to choose it.
 * @property {string} cost - How many evaluations it needs, roughly.
 */

/** @type {Record<string, Guide>} */
export const OPTIMIZATION_GUIDES = {
  SLSQP: {
    family: "Gradient-based, local",
    summary:
      "Sequential quadratic programming: at each iteration, it solves a quadratic model of the objective with linearized constraints, built from the gradients.",
    use: "The usual first choice for smooth problems with inequality or equality constraints, up to a few hundred design variables.",
    cost: "Tens of iterations, each with the gradients of the objective and constraints.",
  },
  NLOPT_SLSQP: {
    family: "Gradient-based, local",
    summary: "The same sequential quadratic programming method as SLSQP, from the NLopt library.",
    use: "An alternative to SciPy's SLSQP when it stops early or behaves badly on a problem.",
    cost: "Tens of iterations, each with the gradients.",
  },
  NLOPT_MMA: {
    family: "Gradient-based, local",
    summary:
      "Method of Moving Asymptotes: each iteration solves a convex, separable approximation of the problem whose moving asymptotes keep the steps safe.",
    use: "Many design variables (thousands and more, as in structural sizing) with inequality constraints; robust and conservative. No equality constraints.",
    cost: "Tens to hundreds of iterations, each with the gradients; its cost barely grows with the number of variables.",
  },
  "L-BFGS-B": {
    family: "Gradient-based, local",
    summary: "A quasi-Newton method keeping a short memory of the gradients to approximate the curvature; it respects the bounds.",
    use: "Smooth problems without constraints other than bounds, including very many design variables.",
    cost: "Tens of iterations, each with a gradient.",
  },
  TNC: {
    family: "Gradient-based, local",
    summary: "Truncated Newton: Newton steps computed approximately from gradients, within the bounds.",
    use: "Smooth problems with bounds only, as an alternative to L-BFGS-B.",
    cost: "Tens of iterations, each with a gradient.",
  },
  NLOPT_BFGS: {
    family: "Gradient-based, local",
    summary: "A limited-memory quasi-Newton method from NLopt, within the bounds.",
    use: "Smooth problems with bounds only.",
    cost: "Tens of iterations, each with a gradient.",
  },
  "NELDER-MEAD": {
    family: "Derivative-free, local",
    summary: "Moves a simplex of n + 1 points by reflections and contractions, using only the values of the objective.",
    use: "Small problems (up to about ten variables) without constraints, with a noisy or non-differentiable objective.",
    cost: "Hundreds of evaluations; slow on larger problems.",
  },
  COBYQA: {
    family: "Derivative-free, local",
    summary: "A trust-region method on quadratic models of the objective and constraints, built from their values only.",
    use: "Constrained problems without derivatives, up to a few tens of variables: often the best derivative-free choice.",
    cost: "Tens of evaluations per design variable.",
  },
  NLOPT_COBYLA: {
    family: "Derivative-free, local",
    summary: "Constrained optimization by linear approximations of the objective and constraints, from their values only.",
    use: "Constrained problems without derivatives, with few variables; simple and robust.",
    cost: "Tens to hundreds of evaluations per design variable.",
  },
  NLOPT_BOBYQA: {
    family: "Derivative-free, local",
    summary: "Bound optimization by quadratic approximation: quadratic models from the values of the objective, within the bounds.",
    use: "Smooth problems without derivatives nor constraints, with few variables.",
    cost: "Tens of evaluations per design variable.",
  },
  NLOPT_NEWUOA: {
    family: "Derivative-free, local",
    summary: "Quadratic models of the objective from its values, as BOBYQA, with bounds handled by NLopt.",
    use: "Smooth problems without derivatives nor constraints, with few variables.",
    cost: "Tens of evaluations per design variable.",
  },
  Augmented_Lagrangian_order_0: {
    family: "Constraint handling",
    summary:
      "Adds the constraints to the objective with multipliers and penalties, then solves a sequence of problems with bounds only, with a derivative-free algorithm.",
    use: "Equality constraints, or constraints that a derivative-free algorithm handles badly.",
    cost: "Several complete sub-optimizations.",
  },
  Augmented_Lagrangian_order_1: {
    family: "Constraint handling",
    summary: "The augmented Lagrangian with a gradient-based algorithm solving the sub-problems.",
    use: "Equality constraints with derivatives, when SLSQP struggles.",
    cost: "Several complete sub-optimizations, with gradients.",
  },
  MNBI: {
    family: "Multi-objective",
    summary:
      "Modified Normal Boundary Intersection: finds points of the Pareto front, the best compromises between the objectives, each by a single-objective optimization.",
    use: "Several objectives: the results show the trade-off between them.",
    cost: "One optimization per point of the front.",
  },
  MultiStart: {
    family: "Global, by restarts",
    summary: "Runs a local algorithm from several starting points drawn by a design of experiments, and keeps the best optimum.",
    use: "Problems with several local optima, when a local algorithm alone gets stuck.",
    cost: "One local optimization per starting point.",
  },
  DIFFERENTIAL_EVOLUTION: {
    family: "Global, evolutionary",
    summary: "A population of designs evolves by mutation, crossover and selection, from the values only.",
    use: "Multimodal or discontinuous problems, with integers, up to a few tens of variables.",
    cost: "Thousands of evaluations.",
  },
  DUAL_ANNEALING: {
    family: "Global, stochastic",
    summary: "Simulated annealing to explore the space, combined with local searches.",
    use: "Multimodal problems with bounds only and few variables.",
    cost: "Thousands of evaluations.",
  },
  SHGO: {
    family: "Global, deterministic",
    summary: "Simplicial homology global optimization: samples the space and locates every basin of attraction, then refines each locally.",
    use: "Smooth problems with a few variables (up to about ten), constraints allowed, when all the local optima matter.",
    cost: "Hundreds to thousands of evaluations; grows fast with the number of variables.",
  },
  INTERIOR_POINT: {
    family: "Linear programming",
    summary: "The HiGHS interior point solver for linear objectives and constraints.",
    use: "Only when the objective and every constraint are linear in the design variables.",
    cost: "Very fast; exact for linear problems.",
  },
  DUAL_SIMPLEX: {
    family: "Linear programming",
    summary: "The HiGHS dual simplex solver for linear objectives and constraints.",
    use: "Only when the objective and every constraint are linear.",
    cost: "Very fast; exact for linear problems.",
  },
  Scipy_MILP: {
    family: "Mixed-integer linear programming",
    summary: "The HiGHS branch-and-bound solver for linear problems with integer variables.",
    use: "Linear objectives and constraints with integer design variables.",
    cost: "Fast for linear problems; grows with the number of integers.",
  },
};

/** @type {Record<string, Guide>} */
export const DOE_GUIDES = {
  LHS: {
    family: "Space-filling, random",
    summary: "Latin hypercube sampling: the range of each variable is cut into as many intervals as samples, and each interval gets one sample.",
    use: "The usual choice: good coverage with few samples, to explore or to train a surrogate.",
    cost: "The number of samples you choose; 10 per variable is a good start.",
  },
  Sobol: {
    family: "Space-filling, quasi-random",
    summary: "A low-discrepancy sequence: points fill the space evenly, and more points refine it without moving the first ones.",
    use: "Even coverage that can be extended; prefer a power of 2 for the number of samples.",
    cost: "The number of samples you choose.",
  },
  Halton: {
    family: "Space-filling, quasi-random",
    summary: "A low-discrepancy sequence built from prime numbers.",
    use: "Even coverage with few variables (up to about ten).",
    cost: "The number of samples you choose.",
  },
  MC: {
    family: "Random",
    summary: "Monte Carlo: independent uniform random samples.",
    use: "Statistics of the outputs, or a simple baseline; less even than LHS.",
    cost: "The number of samples you choose; many for accurate statistics.",
  },
  PoissonDisk: {
    family: "Space-filling, random",
    summary: "Random samples kept at a minimal distance from each other.",
    use: "Even coverage without the alignments of regular grids.",
    cost: "The number of samples you choose.",
  },
  DiagonalDOE: {
    family: "Deterministic",
    summary: "Samples along the diagonal of the space: every variable goes from its lower to its upper bound together.",
    use: "A quick trend, or tests of scalability.",
    cost: "The number of samples you choose.",
  },
  OATDOE: {
    family: "Screening",
    summary: "One factor at a time: from an initial point, each variable moves in turn.",
    use: "A cheap first look at the effect of each variable around a point.",
    cost: "One sample per variable, plus the initial point.",
  },
  MorrisDOE: {
    family: "Screening",
    summary: "Morris trajectories: repeated one-factor-at-a-time paths from random points, to rank the influence of the variables.",
    use: "Finding the influent variables among many, with few evaluations.",
    cost: "Repetitions × (number of variables + 1) samples.",
  },
  CustomDOE: {
    family: "Given samples",
    summary: "Samples you provide, as a file or a list of values.",
    use: "Points chosen elsewhere; the parametric studies use it for their grids.",
    cost: "The samples you give.",
  },
};

/** @type {Record<string, Guide>} */
export const FORMULATION_GUIDES = {
  MDF: {
    family: "Coupled disciplines, solved at each iteration",
    summary: "Multidisciplinary feasible: an MDA solves the couplings at every evaluation, so the optimizer always sees a consistent design.",
    use: "The robust default for coupled disciplines; the optimizer only handles the design variables.",
    cost: "One MDA (several runs of the disciplines) per evaluation.",
  },
  IDF: {
    family: "Coupled disciplines, solved by the optimizer",
    summary:
      "Individual discipline feasible: the coupling variables become design variables, and equality constraints make them consistent at the optimum; the disciplines run independently.",
    use: "Expensive disciplines that can run in parallel, with an algorithm handling equality constraints (SLSQP).",
    cost: "One run of each discipline per evaluation, but more design variables.",
  },
  DisciplinaryOpt: {
    family: "Disciplines in sequence",
    summary: "The disciplines run once, in order, without solving couplings.",
    use: "A single discipline, or disciplines without feedback loops.",
    cost: "One run of each discipline per evaluation.",
  },
  BiLevel: {
    family: "Distributed",
    summary: "A system optimizer handles the shared variables; each discipline optimizes its local variables in a sub-optimization.",
    use: "Large problems split by discipline, as the Sobieski business jet.",
    cost: "Sub-optimizations at each system iteration.",
  },
  BiLevelBCD: {
    family: "Distributed",
    summary: "BiLevel with block coordinate descent: the sub-optimizations run in turn, repeated until they agree.",
    use: "BiLevel problems whose sub-optimizations interact strongly.",
    cost: "Several rounds of sub-optimizations at each system iteration.",
  },
};

/**
 * Algorithms sorted as their guides are: by family, the usual ones first.
 *
 * @template {{name: string}} T
 * @param {"optimization" | "doe" | "formulation"} kind
 * @param {T[]} items
 * @returns {T[]}
 */
export function sortedByGuide(kind, items) {
  const guides = kind === "optimization" ? OPTIMIZATION_GUIDES : kind === "doe" ? DOE_GUIDES : FORMULATION_GUIDES;
  const names = Object.keys(guides);
  const families = [...new Set(Object.values(guides).map((guide) => guide.family))];
  const rank = (/** @type {T} */ item) => {
    const guide = guides[item.name];
    return guide ? [families.indexOf(guide.family), names.indexOf(item.name)] : [families.length, 0];
  };
  return [...items].sort((a, b) => {
    const [familyA, nameA] = rank(a);
    const [familyB, nameB] = rank(b);
    return familyA - familyB || nameA - nameB;
  });
}

/**
 * The guide of an algorithm or formulation.
 *
 * @param {"optimization" | "doe" | "formulation"} kind
 * @param {string} name
 * @returns {Guide | null}
 */
export function guideOf(kind, name) {
  const guides = kind === "optimization" ? OPTIMIZATION_GUIDES : kind === "doe" ? DOE_GUIDES : FORMULATION_GUIDES;
  return guides[name] ?? null;
}

/**
 * @typedef {object} Problem
 * @property {number} variables - The number of design variable elements.
 * @property {number} inequalities
 * @property {number} equalities
 * @property {number} objectives
 * @property {boolean} integers - Whether a design variable is an integer.
 * @property {"exact" | "approximated" | "missing" | ""} derivatives - The worst origin of the derivatives of the components.
 */

/** Beyond this number of design variables, finite differences cost too much. */
const FINITE_DIFFERENCES_LIMIT = 20;
/** Beyond this number of design variables, MMA and L-BFGS-B scale better. */
const MANY_VARIABLES = 200;
/** Beyond this number of design variables, COBYQA becomes slow. */
const DERIVATIVE_FREE_LIMIT = 50;

/**
 * The algorithm suggested for a problem, and why.
 *
 * @param {Problem} problem
 * @param {Set<string>} available - The algorithms that can solve it.
 * @returns {{name: string, reasons: string[]} | null}
 */
export function suggestAlgorithm(problem, available) {
  const reasons = [];
  const variables = `${problem.variables} design variable${problem.variables === 1 ? "" : "s"}`;
  const constraints = problem.inequalities + problem.equalities;
  let name;
  if (problem.objectives > 1) {
    name = "MNBI";
    reasons.push(`${problem.objectives} objectives: the Pareto front of their compromises`);
  } else if (problem.integers) {
    name = "DIFFERENTIAL_EVOLUTION";
    reasons.push("integer design variables: an evolutionary algorithm handles them");
  } else {
    const gradients =
      problem.derivatives === "exact" ||
      problem.derivatives === "" ||
      (problem.derivatives === "approximated" && problem.variables <= FINITE_DIFFERENCES_LIMIT);
    if (problem.derivatives === "exact") {
      reasons.push("the components compute their derivatives");
    } else if (problem.derivatives === "approximated") {
      reasons.push(
        gradients
          ? "derivatives by finite differences, affordable with few variables"
          : "derivatives by finite differences, too costly with many variables",
      );
    } else if (problem.derivatives === "missing") {
      reasons.push("some components have no derivatives");
    }
    if (gradients) {
      if (problem.equalities) {
        name = "SLSQP";
        reasons.push("equality constraints");
      } else if (problem.variables > MANY_VARIABLES) {
        name = problem.inequalities ? "NLOPT_MMA" : "L-BFGS-B";
        reasons.push(`${variables}: it scales to many variables`);
      } else if (problem.inequalities) {
        name = "SLSQP";
        reasons.push(`${variables} and inequality constraints`);
      } else {
        name = "L-BFGS-B";
        reasons.push("bounds only");
      }
    } else if (constraints) {
      name = problem.variables <= DERIVATIVE_FREE_LIMIT ? "COBYQA" : "NLOPT_COBYLA";
      reasons.push(`${variables} and constraints, without derivatives`);
    } else {
      name = "NLOPT_BOBYQA";
      reasons.push("bounds only, without derivatives");
    }
  }
  if (!available.has(name)) {
    return null;
  }
  return { name, reasons };
}

/**
 * The worst origin of the derivatives of some components.
 *
 * @param {string[]} origins - "exact", "approximated", "missing" or "" (unknown).
 * @returns {"exact" | "approximated" | "missing" | ""}
 */
export function worstOrigin(origins) {
  for (const origin of /** @type {const} */ (["missing", "approximated", "exact"])) {
    if (origins.includes(origin)) {
      return origin;
    }
  }
  return "";
}

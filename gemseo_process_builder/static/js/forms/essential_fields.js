// @ts-check
// The settings shown first for common algorithms; the others go to "Advanced".
// Required settings are always shown first; hidden ones are never shown.

/** @type {import("../lib/schema_to_form.js").EssentialTable} */
export const ESSENTIAL_FIELDS = 
{
  "hidden": [
    "callbacks",
    "enable_progress_bar",
    "preprocessors",
    "progress_bar_data_name",
    "use_one_line_progress_bar",
    "differentiated_input_names_substitute",
    "coupling_structure",
    "sub_coupling_structures",
    "linear_solver_settings",
    "inner_mda_settings",
    "main_mda_settings",
    "mdachain_parallel_settings",
    "mda_chain_settings_for_start_at_equilibrium"
  ],
  "kinds": {
    "optimization": {
      "*": ["max_iter", "ftol_rel", "ftol_abs", "xtol_rel", "xtol_abs", "ineq_tolerance", "eq_tolerance"],
      "SLSQP": ["max_iter", "ftol_rel", "ftol_abs", "xtol_rel", "xtol_abs", "ineq_tolerance", "eq_tolerance"],
      "L-BFGS-B": ["max_iter", "ftol_rel", "ftol_abs", "xtol_rel", "xtol_abs"],
      "NELDER-MEAD": ["max_iter", "ftol_rel", "xtol_rel", "adaptive"],
      "COBYQA": ["max_iter", "ftol_rel", "xtol_rel", "initial_tr_radius", "final_tr_radius"],
      "DIFFERENTIAL_EVOLUTION": ["max_iter", "popsize", "seed", "tol"],
      "NLOPT_COBYLA": ["max_iter", "ftol_rel", "xtol_rel", "init_step"]
    },
    "doe": {
      "*": ["n_samples", "seed", "n_processes"],
      "LHS": ["n_samples", "seed", "n_processes", "optimization", "strength"],
      "CustomDOE": ["doe_file", "delimiter", "n_processes"],
      "OATDOE": ["initial_point", "step", "n_processes"],
      "MorrisDOE": ["n_samples", "n_replicates", "step", "seed", "n_processes"]
    },
    "mda": {
      "*": ["tolerance", "max_mda_iter", "inner_mda_name", "warm_start", "n_processes"]
    },
    "formulation": {
      "*": [],
      "MDF": ["main_mda_name"],
      "IDF": ["start_at_equilibrium", "normalize_constraints", "n_processes"],
      "BiLevel": ["main_mda_name", "parallel_scenarios", "reset_x0_before_opt", "set_x0_before_opt"],
      "BiLevelBCD": ["main_mda_name", "parallel_scenarios", "reset_x0_before_opt", "set_x0_before_opt"]
    }
  }
};

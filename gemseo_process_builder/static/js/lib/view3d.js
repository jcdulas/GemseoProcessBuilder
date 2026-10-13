// @ts-check
// The 3D view of nastran_view for evaluations of a run (SPEC § 12.2): when its
// actions are enabled, and why not. Pure, tested with node --test.

/**
 * @typedef {object} View3dState
 * @property {boolean} available - Whether nastran_view is in the Python of the runs.
 * @property {string} [reason] - Why it is not.
 * @property {Record<string, string>} folders - The sizing folder of each evaluation found.
 * @property {string} [store] - The store of gemseo_nastran the folders were looked for in.
 */

/**
 * @typedef {object} View3dAction
 * @property {boolean} enabled
 * @property {string} reason - Why it is disabled; empty when enabled.
 * @property {number[]} evaluations
 */

/**
 * Whether evaluations can be shown, and why not.
 *
 * @param {View3dState | null} state - Null while it is being looked for.
 * @param {number[]} evaluations
 * @returns {string} The reason they cannot; empty when they can.
 */
function blocked(state, evaluations) {
  if (state === null) {
    return "Looking for nastran_view and the folders of the evaluations…";
  }
  if (!state.available) {
    return state.reason || "nastran_view is not installed in the Python of the runs.";
  }
  const missing = evaluations.filter((evaluation) => !state.folders[String(evaluation)]);
  if (missing.length) {
    const where = state.store ? ` in ${state.store}` : "";
    return `No sizing folder of gemseo_nastran for evaluation ${missing.join(" and ")}${where}.`;
  }
  return "";
}

/**
 * The actions on an evaluation: open it, and compare it with another one.
 *
 * @param {View3dState | null} state
 * @param {number} evaluation - The evaluation clicked.
 * @param {number[]} selected - The evaluations selected (brushed) in the views.
 * @returns {{open: View3dAction, compare: View3dAction}}
 */
export function view3dActions(state, evaluation, selected) {
  const others = [...new Set(selected)].filter((item) => item !== evaluation);
  const openReason = blocked(state, [evaluation]);
  let compareReason = "";
  if (others.length !== 1) {
    compareReason = "Select exactly one other evaluation to compare with.";
  } else {
    compareReason = blocked(state, [evaluation, others[0]]);
  }
  return {
    open: { enabled: !openReason, reason: openReason, evaluations: [evaluation] },
    compare: {
      enabled: !compareReason,
      reason: compareReason,
      evaluations: others.length === 1 ? [evaluation, others[0]] : [evaluation],
    },
  };
}

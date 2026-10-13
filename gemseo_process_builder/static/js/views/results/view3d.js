// @ts-check
// The 3D view of nastran_view opened for evaluations of a run (SPEC § 12.2):
// nastran_view is another application, started by the Python side; the page
// only asks for it.
import { app } from "../../app.js";
import { openContextMenu } from "../../components/context_menu.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { view3dActions } from "../../lib/view3d.js";

/** @type {Map<string, Promise<import("../../lib/view3d.js").View3dState>>} */
const states = new Map();
let listening = false;

/**
 * Whether nastran_view is installed, and the folder of each evaluation of a run
 * (asked once per run, again when the runs change).
 *
 * @param {string} runId
 */
export function view3dState(runId) {
  if (!listening) {
    listening = true;
    app.api.on("runs.changed", () => states.clear());
  }
  let state = states.get(runId);
  if (!state) {
    state = app.api
      .call("view3d.state", { run_id: runId }, { timeout: 120_000 })
      .catch((/** @type {any} */ error) => ({ available: false, reason: String(error.message ?? error), folders: {} }));
    states.set(runId, state);
  }
  return state;
}

/**
 * Start nastran_view on one evaluation, or two compared.
 *
 * @param {string} runId
 * @param {number[]} evaluations
 */
function open(runId, evaluations) {
  return app.api
    .call("view3d.open", { run_id: runId, evaluations }, { timeout: 120_000 })
    .catch((/** @type {any} */ error) => showError("nastran_view could not be opened", error));
}

/**
 * The context menu of an evaluation: open it in the 3D view, compare it with
 * the other evaluation selected.
 *
 * @param {MouseEvent} event
 * @param {string} runId
 * @param {number} evaluation
 */
export async function showView3dMenu(event, runId, evaluation) {
  event.preventDefault();
  const { clientX, clientY } = event;
  const state = await view3dState(runId);
  const selected = [...(app.brushSelection.get(runId) ?? [])];
  const actions = view3dActions(state, evaluation, selected);
  openContextMenu(clientX, clientY, [
    {
      label: `Open evaluation ${evaluation} in the 3D view`,
      enabled: actions.open.enabled,
      title: actions.open.reason,
      run: () => open(runId, actions.open.evaluations),
    },
    {
      label: "Compare in the 3D view",
      enabled: actions.compare.enabled,
      title: actions.compare.reason,
      run: () => open(runId, actions.compare.evaluations),
    },
  ]);
}

/**
 * A button opening an evaluation in the 3D view, disabled with its reason.
 *
 * @param {string} runId
 * @param {number} evaluation
 */
export function view3dButton(runId, evaluation) {
  const button = /** @type {HTMLButtonElement} */ (
    el("button.button.bordered", { text: "Open in the 3D view", disabled: true, onClick: () => open(runId, [evaluation]) })
  );
  view3dState(runId).then((state) => {
    const { open: action } = view3dActions(state, evaluation, []);
    button.disabled = !action.enabled;
    button.title = action.reason;
  });
  return button;
}

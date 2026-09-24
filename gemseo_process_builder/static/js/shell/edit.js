// @ts-check
// Edit menu: undo and redo (the selection-based actions come with the canvas).
import { app } from "../app.js";
import { showError } from "../components/errors.js";

/**
 * @param {string} method
 */
async function historyCall(method) {
  try {
    await app.api.call(method);
  } catch (error) {
    showError("The change could not be undone", error);
  }
}

/** @param {{canUndo: boolean, canRedo: boolean}} state */
function showUndoState(state) {
  app.actions.setEnabled("edit.undo", state.canUndo);
  app.actions.setEnabled("edit.redo", state.canRedo);
}

export async function installEditActions() {
  app.actions.handle("edit.undo", { run: () => historyCall("doc.undo"), enabled: false });
  app.actions.handle("edit.redo", { run: () => historyCall("doc.redo"), enabled: false });
  app.api.on("undo.state", showUndoState);
  showUndoState(await app.api.call("doc.undoState"));
}

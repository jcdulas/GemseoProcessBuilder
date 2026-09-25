// @ts-check
// The steps to set up a driver, at the top of its editor: each says what to
// do and has a button doing it or opening the tab where it is done.
import { app } from "../../app.js";
import { openContextMenu } from "../../components/context_menu.js";
import { el } from "../../components/dom.js";
import { DEFAULT_ALGORITHMS, withDefaults } from "../../lib/driver_config.js";
import { driverSteps } from "../../lib/driver_checklist.js";
import { driveNode } from "../../views/canvas/drive.js";

/**
 * A menu of the nodes next to a driver, to put one of them inside it.
 *
 * @param {any} driver
 * @param {MouseEvent} event
 */
function chooseNodeToDrive(driver, event) {
  const siblings = app.store.children(driver.parent ?? app.store.rootId).filter((node) => node.id !== driver.id);
  openContextMenu(
    event.clientX,
    event.clientY,
    siblings.length
      ? siblings.map((node) => ({ label: node.name, run: () => driveNode(driver.id, node.id) }))
      : [{ label: "No component next to it: open it and add components from the Library", enabled: false, run: () => {} }],
  );
}

/**
 * The steps of a driver, or `null` for a driver set up.
 *
 * @param {any} driver - The driver node of the store.
 * @param {(tab: string) => void} showTab
 */
export function driverChecklist(driver, showTab) {
  const { steps, ready } = driverSteps(
    driver.kind,
    driver.name,
    withDefaults(driver.config),
    app.store.children(driver.id).length,
    DEFAULT_ALGORITHMS[/** @type {keyof DEFAULT_ALGORITHMS} */ (driver.kind)] ?? "",
  );
  const required = steps.filter((step) => !step.optional);
  const done = required.filter((step) => step.done).length;
  const items = steps.map((step, index) => {
    /** @type {HTMLElement[]} */
    const actions = [];
    if (step.id === "children" && !step.done) {
      actions.push(
        el("button.button.bordered.small", { text: "Choose a component…", onClick: (/** @type {MouseEvent} */ event) => chooseNodeToDrive(driver, event) }),
        el("button.button.bordered.small", { text: `Open ${driver.name}`, onClick: () => app.navigation.enter(driver.id) }),
      );
    } else if (step.id !== "children" && (!step.done || step.optional)) {
      actions.push(el("button.button.bordered.small", { text: step.done ? "Change" : "Do it", onClick: () => showTab(step.id) }));
    }
    return el(`li.checklist-step${step.done ? ".done" : ""}${step.optional ? ".optional" : ""}`, {}, [
      el("span.checklist-mark", { text: step.done && !step.optional ? "✓" : String(index + 1) }),
      el("div.checklist-text", {}, [el("div", { text: step.label }), step.done ? null : el("div.form-hint", { text: step.hint })]),
      el("div.checklist-actions", {}, actions),
    ]);
  });
  const box = el("details.driver-checklist", {}, [
    el("summary", {
      text: ready ? `${driver.name} is set up: run it with Run.` : `Set up ${driver.name}: ${done} of ${required.length} steps done`,
    }),
    el("ol.checklist-steps", {}, items),
  ]);
  /** @type {HTMLDetailsElement} */ (box).open = !ready;
  return box;
}

// @ts-check
// Drivers drawn as tiles: putting a node under the control of a driver by
// linking them, and the panel of the links between a driver and its nodes.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { showToast } from "../../components/toast.js";
import { openDriverEditor } from "../../panels/driver_editor/index.js";
import { closeLinkPanel, frame, show } from "./link_panel.js";

/**
 * Put a node under the control of a driver: it moves into the driver, and
 * stays where it is drawn (the nodes of a driver share the coordinates of the level).
 *
 * @param {string} driverId
 * @param {string} nodeId
 */
export async function driveNode(driverId, nodeId) {
  const driver = app.store.node(driverId);
  const node = app.store.node(nodeId);
  if (!driver || !node || node.parent === driverId) {
    return;
  }
  try {
    await app.store.execute({ type: "reparentNodes", placements: [{ id: nodeId, parent: driverId }] });
    showToast({ title: `${driver.name} drives ${node.name}`, message: "Its variables can now be design variables, objectives or constraints." });
  } catch (error) {
    showError(`${driver.name} cannot drive ${node.name}`, error);
  }
}

/**
 * Take a node out of its driver: it goes back to the level of the driver.
 *
 * @param {string} driverId
 * @param {string} nodeId
 */
export async function stopDriving(driverId, nodeId) {
  const driver = app.store.node(driverId);
  if (!driver?.parent) {
    return;
  }
  try {
    await app.store.execute({ type: "reparentNodes", placements: [{ id: nodeId, parent: driver.parent }] });
    closeLinkPanel();
  } catch (error) {
    showError("The node could not be moved", error);
  }
}

/**
 * The panel of a link between a driver and a node it drives: the variables
 * with their role, and the actions.
 *
 * @param {import("../../lib/scene.js").SceneLink} link
 * @param {number} x
 * @param {number} y
 */
export function openDriverLinkPanel(link, x, y) {
  const driverId = /** @type {string} */ (link.driver);
  const driver = app.store.node(driverId);
  const nodeId = link.from === driverId ? link.to : link.from;
  const node = app.store.node(nodeId);
  const from = app.store.node(link.from);
  const to = app.store.node(link.to);
  const content = [];
  if (link.kind === "control") {
    content.push(
      el("p.form-hint", {
        text: `${driver?.name} runs ${node?.name}, which exchanges no variable with it: it computes what the other nodes need.`,
      }),
    );
  } else {
    content.push(
      el("table.link-panel-table", {}, [
        el("tr", {}, [el("th", { text: "Variable" }), el("th", { text: "Role" })]),
        ...link.variables.map((/** @type {any} */ variable) =>
          el("tr", {}, [el("td", { text: variable.name }), el("td.form-hint", { text: variable.role })]),
        ),
      ]),
    );
  }
  content.push(
    el("div.link-panel-actions", {}, [
      el("button.button.bordered", {
        text: `Stop driving ${node?.name}`,
        title: `${node?.name} goes back to the level of ${driver?.name}`,
        onClick: () => stopDriving(driverId, nodeId),
      }),
      el("button.button.bordered.primary", {
        text: `Edit ${driver?.name}…`,
        onClick: () => {
          closeLinkPanel();
          openDriverEditor(driverId);
        },
      }),
    ]),
  );
  show(frame(`${from?.name} → ${to?.name}`, content), x, y);
}

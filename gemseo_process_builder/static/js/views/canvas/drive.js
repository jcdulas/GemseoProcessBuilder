// @ts-check
// Putting a node under the control of a driver by linking them: the node
// moves into the driver.
import { app } from "../../app.js";
import { showError } from "../../components/errors.js";
import { showToast } from "../../components/toast.js";

/**
 * Put a node under the control of a driver: it moves into the driver.
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

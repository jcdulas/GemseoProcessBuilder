// @ts-check
// Roles of the variables in their driver (design variable, objective…).
import { app } from "../app.js";
import { showError } from "../components/errors.js";
import { enclosingDriver, roleChoices } from "../lib/driver_config.js";
import { openDriverEditor } from "../panels/driver_editor/index.js";

export class DriverRoles {
  constructor() {
    /** @type {Record<string, string[]>} */
    this.roles = {};
    /** @type {Set<() => void>} */
    this.listeners = new Set();
    app.api.on("resolution.updated", () => this.refresh());
    app.store.subscribe((event) => {
      if (event.type === "reset") {
        this.refresh();
      }
    });
    this.refresh();
  }

  async refresh() {
    try {
      this.roles = await app.api.call("driver.portRoles");
    } catch (error) {
      console.error(error);
      return;
    }
    for (const listener of this.listeners) {
      listener();
    }
  }

  /**
   * The roles of a port of a component.
   *
   * @param {string} nodeId
   * @param {string} direction
   * @param {string} port
   * @returns {string[]}
   */
  of(nodeId, direction, port) {
    return this.roles[`${nodeId}/${direction}/${port}`] ?? [];
  }

  /** @param {() => void} listener */
  onChange(listener) {
    this.listeners.add(listener);
  }
}

/**
 * Menu items giving a port a role in the driver containing its component.
 *
 * @param {string} nodeId
 * @param {string} port
 * @param {"in" | "out"} direction
 * @returns {import("../components/context_menu.js").MenuItem[]}
 */
export function roleMenuItems(nodeId, port, direction) {
  const driver = enclosingDriver(app.store.pathTo(nodeId), (id) => app.store.node(id));
  if (!driver) {
    return [];
  }
  return roleChoices(driver.kind, direction).map(({ role, label }) => ({
    label: `${label} of ${driver.name}`,
    run: () => assignRole(nodeId, port, direction, role),
  }));
}

/**
 * Give a port a role, then show it in the driver editor.
 *
 * @param {string} node
 * @param {string} port
 * @param {"in" | "out"} direction
 * @param {string} role
 */
export async function assignRole(node, port, direction, role) {
  try {
    const { driver, field } = await app.api.call("driver.assignRole", { node, port, direction, role });
    openDriverEditor(driver, field);
  } catch (error) {
    showError("The role could not be given", error);
  }
}

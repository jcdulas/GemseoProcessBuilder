// @ts-check
// The links of a driver drawn as a tile: the variables it sends to the nodes
// it drives (design variables, parameters) and those it gets back from them
// (objectives, constraints, observables, responses).

/**
 * @typedef {object} DriverVariable
 * @property {string} name - The global name.
 * @property {string} role - design variable, parameter, objective, constraint,
 *   observable or response.
 */

/**
 * @typedef {object} DriverLink
 * @property {string} source - The driver, or the node sending results to it.
 * @property {string} target
 * @property {DriverVariable[]} variables - Empty for a control link.
 * @property {boolean} control - The driver drives the node, which exchanges
 *   no variable with it.
 */

/**
 * The variables a driver sends to the nodes it drives, and those it gets back.
 *
 * @param {string} kind - optimization, doe, parametric or mda.
 * @param {any} config - The driver configuration (`DriverConfig`).
 * @returns {{sent: DriverVariable[], received: DriverVariable[]}}
 */
export function driverVariables(kind, config) {
  const names = (/** @type {any[] | undefined} */ items, /** @type {string} */ role) =>
    (items ?? []).map((item) => ({ name: typeof item === "string" ? item : item.variable, role }));
  if (kind === "optimization") {
    return {
      sent: names(config?.design_space, "design variable"),
      received: [
        ...names(config?.objectives, "objective"),
        ...names(config?.constraints, "constraint"),
        ...names(config?.observables, "observable"),
      ],
    };
  }
  if (kind === "doe") {
    return {
      sent: names(config?.design_space, "design variable"),
      received: [...names(config?.responses, "response"), ...names(config?.observables, "observable")],
    };
  }
  if (kind === "parametric") {
    return { sent: names(config?.levels, "parameter"), received: names(config?.responses, "response") };
  }
  return { sent: [], received: [] };
}

/**
 * The global names of the inputs or outputs of a node, from the view of the
 * scope holding it: a map from local to global names for a component, a list
 * for a container.
 *
 * @param {any} ports - `LevelView.ports[node]`.
 * @param {"in" | "out"} direction
 * @returns {Set<string>}
 */
function globalNames(ports, direction) {
  const side = ports?.[direction];
  if (!side) {
    return new Set();
  }
  return new Set(Array.isArray(side) ? side : Object.values(side));
}

/**
 * The links between a driver and the nodes it drives.
 *
 * @param {{id: string, kind: string, config: any, children: string[]}} driver
 * @param {{ports: Record<string, any>} | undefined} view - The resolved view of
 *   the scope of the driver (`resolve.level` of the driver).
 * @returns {DriverLink[]}
 */
export function driverLinks(driver, view) {
  const { sent, received } = driverVariables(driver.kind, driver.config);
  /** @type {DriverLink[]} */
  const links = [];
  for (const child of driver.children) {
    const ports = view?.ports[child];
    const inputs = globalNames(ports, "in");
    const outputs = globalNames(ports, "out");
    const driven = sent.filter((variable) => inputs.has(variable.name));
    const results = received.filter((variable) => outputs.has(variable.name));
    if (driven.length) {
      links.push({ source: driver.id, target: child, variables: driven, control: false });
    }
    if (results.length) {
      links.push({ source: child, target: driver.id, variables: results, control: false });
    }
    if (!driven.length && !results.length) {
      links.push({ source: driver.id, target: child, variables: [], control: true });
    }
  }
  return links;
}

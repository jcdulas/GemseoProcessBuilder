// @ts-check
// Suggestions of common units while typing one (any pint unit is accepted:
// Python checks it).
import { app } from "../app.js";
import { el } from "./dom.js";

export const UNIT_LIST_ID = "unit-suggestions";

/**
 * The ``<datalist>`` of common units, created once (inputs refer to it by id).
 *
 * @returns {string} Its id.
 */
export function unitList() {
  if (!document.getElementById(UNIT_LIST_ID)) {
    const list = el("datalist", { id: UNIT_LIST_ID });
    document.body.append(list);
    app.api
      .call("units.suggestions", { prefix: "" })
      .then((/** @type {string[]} */ units) => list.replaceChildren(...units.map((unit) => el("option", { value: unit }))))
      .catch((/** @type {unknown} */ error) => console.error(error));
  }
  return UNIT_LIST_ID;
}

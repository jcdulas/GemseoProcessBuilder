// @ts-check
// The Interface tab of a driver inside another node (SPEC § 6.3): what the
// parent sets before each run of the driver, and what it reads after.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { interfaceCandidates } from "../../lib/driver_config.js";
import { pickButton, setConfig, tabHeader } from "./common.js";

/** @type {Record<string, string>} */
const KIND_NAMES = { optimization: "optimization", doe: "design of experiments", parametric: "parametric study" };

/** The adapter settings, with what they do. */
const ADAPTER_SETTINGS = [
  { key: "reset_x0_before_opt", label: "Start each run from the initial design", title: "Otherwise, each run starts from the result of the previous one." },
  { key: "set_x0_before_opt", label: "Start each run from the values set by the parent", title: "Useful for multi-start optimizations; the parent sets the design variables." },
  { key: "set_bounds_before_opt", label: "Take the bounds from the parent", title: "The parent sets the bounds of the design variables (trust regions)." },
  { key: "keep_opt_history", label: "Keep the history of every run", title: "Memory consuming when the driver runs many times." },
];

/**
 * A list of variable names with a remove button each.
 *
 * @param {string[]} names
 * @param {string} empty - Shown when the list is empty.
 * @param {(name: string) => void} remove
 */
function nameList(names, empty, remove) {
  if (!names.length) {
    return el("p.placeholder", { text: empty });
  }
  return el(
    "ul.interface-list",
    {},
    names.map((name) =>
      el("li.interface-item", {}, [
        el("span.interface-name", { text: name }),
        el("button.table-button", { text: "×", title: `Remove ${name}`, onClick: () => remove(name) }),
      ]),
    ),
  );
}

/** @param {import("./common.js").TabContext} context */
export function interfaceTab(context) {
  const element = el("div.driver-tab.driver-scroll");
  /** @param {import("./common.js").TabContext} current */
  const render = (current) => {
    const driver = current.driver;
    const parent = app.store.node(driver.parent);
    if (current.placement === "bilevel") {
      element.replaceChildren(
        tabHeader(
          `${parent?.name ?? "The system"} uses the BiLevel formulation: it chooses what ${driver.name} exchanges with it. ` +
            "It sets the shared design variables and the couplings, and reads back the outputs and the design variables of this sub-optimization.",
        ),
      );
      return;
    }
    const id = driver.id;
    const interfaceConfig = { inputs: [], outputs: [], ...current.config.interface };
    /** @param {Record<string, any>} values */
    const save = (values) =>
      setConfig(id, "interface", { ...interfaceConfig, ...values }).catch((error) => showError("The interface could not be changed", error));
    const candidates = async () => interfaceCandidates(await current.variables(), current.config);
    const settings = ADAPTER_SETTINGS.map(({ key, label, title }) => {
      const box = /** @type {HTMLInputElement} */ (el("input", { type: "checkbox", checked: Boolean(interfaceConfig[key]) }));
      box.addEventListener("change", () => {
        const values = { [key]: box.checked };
        // GEMSEO accepts one way to choose the starting point, not both.
        if (box.checked && key === "reset_x0_before_opt") {
          values.set_x0_before_opt = false;
        } else if (box.checked && key === "set_x0_before_opt") {
          values.reset_x0_before_opt = false;
        }
        save(values);
      });
      return el("label.form-row.form-check", { title }, [box, el("span", { text: label })]);
    });
    element.replaceChildren(
      tabHeader(
        `${driver.name} runs inside ${parent?.name ?? "its parent"}: each time ${parent?.name ?? "it"} executes it, ` +
          `it sets the inputs below, the whole ${KIND_NAMES[driver.kind] ?? "study"} runs, and the outputs below are given back.`,
      ),
      el("h3.section-title", { text: "Inputs set by the parent" }),
      nameList(interfaceConfig.inputs, "No input: the driver always runs with the same values.", (name) =>
        save({ inputs: interfaceConfig.inputs.filter((/** @type {string} */ item) => item !== name) }),
      ),
      el("div.driver-tab-buttons", {}, [
        pickButton(
          "Add input",
          async () => (await candidates()).inputs,
          () => interfaceConfig.inputs,
          (name) => save({ inputs: [...interfaceConfig.inputs, name] }),
        ),
      ]),
      el("h3.section-title", { text: "Outputs given back" }),
      nameList(interfaceConfig.outputs, "No output yet: the parent cannot use the results of this driver.", (name) =>
        save({ outputs: interfaceConfig.outputs.filter((/** @type {string} */ item) => item !== name) }),
      ),
      el("div.driver-tab-buttons", {}, [
        pickButton(
          "Add output",
          async () => (await candidates()).outputs,
          () => interfaceConfig.outputs,
          (name) => save({ outputs: [...interfaceConfig.outputs, name] }),
        ),
      ]),
      el("details.form-advanced", { open: ADAPTER_SETTINGS.some(({ key }) => interfaceConfig[key]) }, [
        el("summary", { text: "Advanced" }),
        ...settings,
      ]),
    );
  };
  render(context);
  return { element, update: render };
}

// @ts-check
// Tabs choosing how a driver runs: algorithm, formulation, MDA settings, execution.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { settingsForm } from "../../forms/schema_form.js";
import { DEFAULT_ALGORITHMS, DEFAULT_FORMULATIONS } from "../../lib/driver_config.js";
import { setConfig, tabHeader } from "./common.js";

/**
 * A settings form that validates its values with Pydantic in the worker.
 *
 * @param {HTMLElement} container - Replaced by the form.
 * @param {{kind: string, name: string, settings: Record<string, any>, save: (settings: Record<string, any>) => Promise<unknown>}} options
 */
async function showSettings(container, { kind, name, settings, save }) {
  const focused = /** @type {HTMLElement | null} */ (container.querySelector(":focus"));
  const focusName = focused?.getAttribute("name");
  let form;
  try {
    const schema = await app.api.call("settings.schema", { kind, name }, { timeout: 120_000 });
    form = settingsForm({ schema, kind, name, settings, onChange: (next) => save(next).catch(() => {}) });
  } catch (error) {
    container.replaceChildren(el("p.placeholder", { text: `The settings of ${name} cannot be shown: ${String(error)}` }));
    return;
  }
  container.replaceChildren(form.element);
  if (focusName) {
    /** @type {HTMLElement | null} */ (form.element.querySelector(`[name="${CSS.escape(focusName)}"]`))?.focus();
  }
  if (Object.keys(settings).length) {
    app.api
      .call("settings.validate", { kind, name, settings }, { timeout: 120_000 })
      .then((errors) => form.showErrors(errors))
      .catch((error) => console.error(error));
  }
}

/**
 * A tab choosing an algorithm (or a formulation) and editing its settings.
 *
 * @param {import("./common.js").TabContext} context
 * @param {{field: "algorithm" | "formulation", kind: string, defaultName: string, hint: string}} options
 */
function choiceTab(context, { field, kind, defaultName, hint }) {
  const id = context.driver.id;
  const select = /** @type {HTMLSelectElement} */ (el("select.select"));
  const about = el("p.form-hint");
  const settings = el("div.driver-settings", {}, [el("p.placeholder", { text: "Loading…" })]);
  const element = el("div.driver-tab.driver-scroll", {}, [
    tabHeader(hint),
    el("label.form-row", {}, [el("span.form-label", { text: field === "algorithm" ? "Algorithm" : "Formulation" }), select]),
    about,
    settings,
  ]);
  let choice = context.config[field];
  /** @type {any[]} */
  let items = [];
  const current = () => choice.name || defaultName;

  const describe = () => {
    const item = items.find((candidate) => candidate.name === current());
    about.textContent = item ? [item.library, item.description].filter(Boolean).join(" — ") : "";
  };
  const fillSelect = () => {
    select.replaceChildren(
      ...items.map((item) =>
        el("option", {
          value: item.name,
          // A disabled option shows no tooltip: the reason is in its text.
          text: item.reasons?.length ? `${item.name} — ${item.reasons.join(", ")}` : item.name,
          disabled: item.reasons?.length > 0 && item.name !== current(),
          selected: item.name === current(),
        }),
      ),
    );
    describe();
  };
  const loadList = () =>
    app.api
      .call("driver.algorithms", { id, kind }, { timeout: 120_000 })
      .then((list) => {
        items = list;
        fillSelect();
      })
      .catch((error) => {
        about.textContent = `The list cannot be loaded: ${String(error)}`;
      });
  const loadSettings = () =>
    showSettings(settings, {
      kind,
      name: current(),
      settings: choice.settings ?? {},
      save: (next) => setConfig(id, field, { name: current(), settings: next }),
    });

  select.addEventListener("change", () => {
    setConfig(id, field, { name: select.value, settings: {} }).catch(() => {
      select.value = current();
    });
  });
  loadList();
  loadSettings();
  return {
    element,
    update: (/** @type {import("./common.js").TabContext} */ next) => {
      const previous = choice;
      choice = next.config[field];
      if (JSON.stringify(previous) === JSON.stringify(choice)) {
        loadList(); // Other changes (constraints…) change which algorithms fit.
        return;
      }
      fillSelect();
      loadSettings();
    },
  };
}

/** @param {import("./common.js").TabContext} context */
export function algorithmTab(context) {
  const kind = context.driver.kind === "doe" ? "doe" : "optimization";
  return choiceTab(context, {
    field: "algorithm",
    kind,
    defaultName: DEFAULT_ALGORITHMS[/** @type {"doe" | "optimization"} */ (context.driver.kind)] ?? "",
    hint:
      kind === "doe"
        ? "The sampling method; its settings include the number of samples."
        : "Algorithms that cannot solve this problem (constraints, several objectives, integers) cannot be chosen.",
  });
}

/** @param {import("./common.js").TabContext} context */
export function formulationTab(context) {
  return choiceTab(context, {
    field: "formulation",
    kind: "formulation",
    defaultName: DEFAULT_FORMULATIONS[/** @type {"doe" | "optimization"} */ (context.driver.kind)] ?? "MDF",
    hint: "How the coupled disciplines are solved during the study: MDF runs an MDA at each iteration.",
  });
}

/** @param {import("./common.js").TabContext} context */
export function mdaTab(context) {
  const id = context.driver.id;
  const settings = el("div.driver-settings");
  let current = context.config.mda_settings;
  const load = () =>
    showSettings(settings, {
      kind: "mda",
      name: "MDAChain",
      settings: current,
      save: (next) => setConfig(id, "mda_settings", next),
    });
  load();
  return {
    element: el("div.driver-tab.driver-scroll", {}, [
      tabHeader("The MDA runs the disciplines once, iterating until the coupled variables agree."),
      settings,
    ]),
    update: (/** @type {import("./common.js").TabContext} */ next) => {
      if (JSON.stringify(next.config.mda_settings) !== JSON.stringify(current)) {
        current = next.config.mda_settings;
        load();
      }
    },
  };
}

/** @param {import("./common.js").TabContext} context */
export function executionTab(context) {
  const id = context.driver.id;
  const execution = context.config.execution;
  /** @param {Record<string, any>} values */
  const save = (values) =>
    setConfig(id, "execution", { ...execution, ...values }).catch((error) => showError("The option could not be changed", error));
  const processes = /** @type {HTMLInputElement} */ (
    el("input.input", { type: "number", min: 1, step: 1, value: execution.n_processes ?? 1, name: "n_processes" })
  );
  processes.addEventListener("change", () => save({ n_processes: Math.max(1, Math.round(Number(processes.value) || 1)) }));
  const history = /** @type {HTMLInputElement} */ (el("input", { type: "checkbox", checked: execution.save_history !== false }));
  history.addEventListener("change", () => save({ save_history: history.checked }));
  const folder = /** @type {HTMLInputElement} */ (
    el("input.input", { type: "text", value: execution.working_directory ?? "", placeholder: "the run folder" })
  );
  folder.addEventListener("change", () => save({ working_directory: folder.value.trim() }));
  return {
    element: el("div.driver-tab.driver-scroll", {}, [
      tabHeader("How the study runs."),
      el("label.form-row", { title: "Evaluations run at the same time" }, [el("span.form-label", { text: "Processes" }), processes]),
      el("label.form-row.form-check", {}, [history, el("span", { text: "Save the optimization history" })]),
      el("label.form-row", {}, [el("span.form-label", { text: "Working folder" }), folder]),
    ]),
  };
}

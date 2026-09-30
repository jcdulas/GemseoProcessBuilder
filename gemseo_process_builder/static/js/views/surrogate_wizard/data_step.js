// @ts-check
// Step 1 of the surrogate wizard: the run to learn from and its variables.
// By default, the inputs are the variables the run varied (its design
// variables) and the outputs are the others.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";

/** The fewest evaluations a surrogate can learn from. */
const MIN_SAMPLES = 3;

export class DataStep {
  /**
   * @param {HTMLElement} page
   * @param {import("./wizard.js").SurrogateWizard} wizard
   */
  constructor(page, wizard) {
    this.page = page;
    this.wizard = wizard;
    /** @type {any[]} */
    this.runs = [];
    /** @type {any} - surrogates.variables of the chosen run. */
    this.variables = null;
    this.loadedRun = "";
  }

  async render() {
    const state = this.wizard.state;
    try {
      const { runs } = await app.api.call("runs.list");
      this.runs = runs.filter((/** @type {any} */ run) => !run.missing && run.status === "completed");
      if (state.run && state.run !== this.loadedRun) {
        await this.loadVariables(state.run, !state.inputs.length);
      }
    } catch (error) {
      showError("The runs could not be read", error);
    }
    this.draw();
  }

  /**
   * @param {string} run
   * @param {boolean} chooseDefaults - Take the default inputs and outputs.
   */
  async loadVariables(run, chooseDefaults) {
    const state = this.wizard.state;
    this.variables = null;
    this.loadedRun = run;
    this.variables = await app.api.call("surrogates.variables", { run }, { timeout: 120_000 });
    const names = (/** @type {any[]} */ items) => items.map((item) => item.name);
    if (chooseDefaults) {
      state.inputs = names(this.variables.inputs);
      state.outputs = names(this.variables.outputs);
    } else {
      // A retrained surrogate keeps the variables the run still has.
      const known = new Set([...names(this.variables.inputs), ...names(this.variables.outputs)]);
      state.inputs = state.inputs.filter((name) => known.has(name));
      state.outputs = state.outputs.filter((name) => known.has(name));
    }
  }

  draw() {
    const state = this.wizard.state;
    const select = /** @type {HTMLSelectElement} */ (
      el("select.select", {}, [
        el("option", { value: "", text: this.runs.length ? "Choose a run…" : "No completed run" }),
        ...this.runs.map((run) =>
          el("option", {
            value: run.id,
            text: `${run.name || run.id} — ${run.driver_path || run.driver_name} (${run.summary?.n_evaluations ?? "?"} evaluations)`,
          }),
        ),
      ])
    );
    select.value = state.run;
    select.addEventListener("change", async () => {
      state.run = select.value;
      try {
        if (state.run) {
          await this.loadVariables(state.run, true);
        } else {
          this.variables = null;
        }
      } catch (error) {
        showError("The variables of the run could not be read", error);
      }
      this.wizard.changed();
    });
    /** @type {(Node | null)[]} */
    const parts = [el("h3.section-title", { text: "Training data" }), el("label.form-row", {}, [el("span.form-label", { text: "Run" }), select])];
    if (state.replaceId && !state.run) {
      parts.push(el("p.form-hint", { text: "The run of this surrogate was deleted: choose another run to retrain it." }));
    }
    if (this.variables) {
      const samples = this.variables.n_samples;
      parts.push(
        el(`p.form-hint${samples < MIN_SAMPLES ? ".form-error" : ""}`, {
          text: samples < MIN_SAMPLES ? `The run has ${samples} evaluations: at least ${MIN_SAMPLES} are needed.` : `${samples} evaluations to learn from (failed ones are left out).`,
        }),
        el("div.wizard-columns", {}, [
          this.checklist("Inputs", "The variables the surrogate takes.", "inputs"),
          this.checklist("Outputs", "The variables the surrogate predicts.", "outputs"),
        ]),
      );
    }
    this.page.replaceChildren(el("div.wizard-form", {}, parts));
  }

  /**
   * Checkboxes choosing variables of the run.
   *
   * @param {string} title
   * @param {string} hint
   * @param {"inputs" | "outputs"} key
   */
  checklist(title, hint, key) {
    const state = this.wizard.state;
    const items = [...this.variables.inputs, ...this.variables.outputs];
    const other = key === "inputs" ? state.outputs : state.inputs;
    return el("div.wizard-list", {}, [
      el("h4", { text: title }),
      el("div.form-hint", { text: hint }),
      ...items
        .filter((item) => !other.includes(item.name))
        .map((item) => {
          const box = /** @type {HTMLInputElement} */ (el("input", { type: "checkbox" }));
          box.checked = state[key].includes(item.name);
          box.addEventListener("change", () => {
            state[key] = box.checked ? [...state[key], item.name] : state[key].filter((name) => name !== item.name);
            this.wizard.changed();
          });
          const size = item.size > 1 ? ` (${item.size})` : "";
          return el("label.wizard-check", { title: item.role }, [box, el("span", { text: `${item.name}${size}` }), el("span.form-hint", { text: item.role })]);
        }),
    ]);
  }
}

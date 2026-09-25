// @ts-check
// The "Build surrogate" wizard (SPEC § 7.4): a center tab going through
// 1. the run and its variables, 2. the algorithm and its settings, 3. the
// training and its quality, 4. the name the surrogate is saved under.
//
// Opened from a run (Runs panel, Results tab), from a surrogate component (its
// inspector), or to retrain a surrogate, pre-filled with its metadata.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { AlgorithmStep } from "./algorithm_step.js";
import { DataStep } from "./data_step.js";
import { QualityStep } from "./quality_step.js";

const STEPS = [
  { id: "data", label: "1. Data" },
  { id: "algorithm", label: "2. Algorithm" },
  { id: "quality", label: "3. Training and quality" },
  { id: "save", label: "4. Save" },
];

/**
 * @typedef {object} WizardState
 * @property {string} run - The id of the training run.
 * @property {string[]} inputs
 * @property {string[]} outputs
 * @property {string} algorithm
 * @property {Record<string, any>} settings
 * @property {number} nFolds
 * @property {any} result - What surrogates.train returned, once trained.
 * @property {string} name
 * @property {string} nodeId - The surrogate component to give the surrogate to.
 * @property {string} replaceId - The surrogate being retrained.
 */

/** @type {Map<string, SurrogateWizard>} */
const opened = new Map();

export class SurrogateWizard {
  /**
   * @param {HTMLElement} page
   * @param {WizardState} state
   */
  constructor(page, state) {
    this.page = page;
    this.state = state;
    this.step = "data";
    this.bar = el("div.results-tabs");
    /** @type {Record<string, HTMLElement>} */
    this.pages = Object.fromEntries(STEPS.map((step) => [step.id, el("div.results-page.wizard-page")]));
    /** @type {Record<string, {render: () => void}>} */
    this.steps = {
      data: new DataStep(this.pages.data, this),
      algorithm: new AlgorithmStep(this.pages.algorithm, this),
      quality: new QualityStep(this.pages.quality, this),
      save: { render: () => this.renderSave() },
    };
    this.footer = el("div.wizard-footer");
    page.classList.add("results-tab", "surrogate-wizard");
    page.replaceChildren(this.bar, ...Object.values(this.pages), this.footer);
    this.show("data");
  }

  /** Whether a step can be shown, given what was chosen before it. */
  reachable(/** @type {string} */ step) {
    const { run, inputs, outputs, algorithm, result } = this.state;
    const data = Boolean(run && inputs.length && outputs.length);
    return {
      data: true,
      algorithm: data,
      quality: data && Boolean(algorithm),
      save: Boolean(result),
    }[step];
  }

  /** @param {string} step */
  show(step) {
    this.step = step;
    this.bar.replaceChildren(
      ...STEPS.map((item) => {
        const button = el(`button.driver-tab-button${item.id === step ? ".active" : ""}`, { text: item.label, onClick: () => this.show(item.id) });
        button.toggleAttribute("disabled", !this.reachable(item.id));
        return button;
      }),
    );
    for (const [id, element] of Object.entries(this.pages)) {
      element.hidden = id !== step;
    }
    this.steps[step].render();
    this.renderFooter();
  }

  /** The choices changed: the trained model no longer matches them. */
  changed() {
    this.state.result = null;
    this.show(this.step);
  }

  renderFooter() {
    const index = STEPS.findIndex((item) => item.id === this.step);
    const back = el("button.button.bordered", { text: "Back", onClick: () => this.show(STEPS[index - 1].id) });
    back.toggleAttribute("disabled", index === 0);
    const nextStep = STEPS[index + 1];
    const next = nextStep ? el("button.button.bordered.primary", { text: "Next", onClick: () => this.show(nextStep.id) }) : null;
    next?.toggleAttribute("disabled", !this.reachable(nextStep.id));
    this.footer.replaceChildren(el("span.toolbar-spacer"), back, next ?? el("span"));
  }

  renderSave() {
    const state = this.state;
    const name = /** @type {HTMLInputElement} */ (el("input.input", { type: "text", spellcheck: "false" }));
    name.value = state.name;
    name.addEventListener("input", () => (state.name = name.value));
    const node = state.nodeId ? app.store.node(state.nodeId) : null;
    const target = state.replaceId
      ? "It replaces the surrogate being retrained; the components using it follow."
      : node
        ? `${node.name} will use it.`
        : "Add it to the model after saving, or give it later to a Surrogate component.";
    const message = el("div.form-hint");
    const save = el("button.button.bordered.primary", { text: "Save surrogate", onClick: () => this.save(name.value, message) });
    this.pages.save.replaceChildren(
      el("div.wizard-form", {}, [
        el("h3.section-title", { text: "Save" }),
        el("label.form-row", {}, [el("span.form-label", { text: "Name" }), name]),
        el("p.form-hint", { text: `Saved with the project, in its .surrogates folder. ${target}` }),
        el("div.wizard-actions", {}, [save]),
        message,
      ]),
    );
    name.focus();
  }

  /**
   * @param {string} name
   * @param {HTMLElement} message
   */
  async save(name, message) {
    const state = this.state;
    try {
      const saved = await app.api.call("surrogates.save", {
        trained: state.result.trained,
        name,
        run: state.run,
        algorithm: state.algorithm,
        settings: state.settings,
        result: state.result,
        replace: state.replaceId,
        node: state.nodeId,
      });
      state.replaceId = saved.id;
      const actions = [];
      if (!state.nodeId) {
        actions.push(
          el("button.button.bordered.primary", {
            text: "Add to model",
            title: "Add a component using the surrogate at the level shown",
            onClick: async () => {
              try {
                state.nodeId = await app.api.call("surrogates.add", { parent: app.navigation.current(), id: saved.id });
                app.selection.set([state.nodeId]);
                message.replaceChildren(el("span", { text: "Added to the model." }));
              } catch (error) {
                showError("The surrogate could not be added", error);
              }
            },
          }),
        );
      }
      message.replaceChildren(el("span", { text: `Saved in ${saved.model_path}.` }), ...actions);
    } catch (error) {
      showError("The surrogate could not be saved", error);
    }
  }
}

/**
 * Open the wizard.
 *
 * @param {{run?: string, nodeId?: string, retrain?: any}} [options] - ``retrain``
 *   is an entry of surrogates.list.
 */
export function openSurrogateWizard({ run = "", nodeId = "", retrain = null } = {}) {
  const metadata = retrain?.metadata;
  const key = retrain ? `retrain-${retrain.id}` : nodeId || run || "new";
  /** @type {WizardState} */
  const state = {
    run: metadata ? (metadata.source.deleted ? "" : metadata.source.id) : run,
    inputs: metadata ? metadata.inputs.map((/** @type {any} */ item) => item.name) : [],
    outputs: metadata ? metadata.outputs.map((/** @type {any} */ item) => item.name) : [],
    algorithm: metadata?.algorithm ?? "RBFRegressor",
    settings: metadata?.settings ?? {},
    nFolds: metadata?.n_folds ?? 5,
    result: null,
    name: metadata?.name ?? (nodeId ? (app.store.node(nodeId)?.name ?? "") : ""),
    nodeId,
    replaceId: retrain?.id ?? "",
  };
  const existing = opened.get(key);
  if (existing) {
    app.tabs.center.activate(`surrogate-${key}`);
    return existing;
  }
  const page = app.tabs.center.open({
    id: `surrogate-${key}`,
    title: retrain ? `Retrain ${retrain.name}` : "Build surrogate",
    onClose: () => opened.delete(key),
  });
  const wizard = new SurrogateWizard(page, state);
  opened.set(key, wizard);
  return wizard;
}

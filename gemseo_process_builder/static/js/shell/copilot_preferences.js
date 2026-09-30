// @ts-check
// Preferences › Claude copilot: how to reach Claude, the models, the defaults
// of a new copilot (docs/CLAUDE_PILOT_SPEC.md § 5, § 10.1).
import { app } from "../app.js";
import { el } from "../components/dom.js";
import { showError } from "../components/errors.js";
import { DATA_LEVELS, DEFAULT_MODEL, EFFORTS, MODELS, MODES, withValue } from "../lib/copilot.js";
import { checkBackend } from "../panels/driver_editor/copilot_tab.js";
import { preferenceSections } from "./preferences_dialog.js";

/** @type {{id: string, label: string, hint: string}[]} */
const BACKENDS = [
  {
    id: "claude_code",
    label: "Claude Code (subscription)",
    hint: "Your own Claude Code, logged in with your Claude account: install it, then run claude in a terminal once to log in.",
  },
  {
    id: "api_key",
    label: "API key",
    hint: "An Anthropic API key, billed per token; kept in the keyring of your system, or read from ANTHROPIC_API_KEY.",
  },
];

/**
 * @param {string} label
 * @param {HTMLElement} control
 * @param {string} [hint]
 */
function row(label, control, hint) {
  return el("div.pref-row", {}, [
    el("label.form-label", { text: label }),
    el("div", {}, [control, hint ? el("div.form-hint", { text: hint }) : null]),
  ]);
}

/**
 * @param {string} name
 * @param {{id: string, label: string}[]} choices
 * @param {string} value
 */
function select(name, choices, value) {
  return /** @type {HTMLSelectElement} */ (
    el(
      "select.input",
      { name },
      choices.map((choice) => el("option", { value: choice.id, text: choice.label, selected: choice.id === value })),
    )
  );
}

/** @param {Record<string, any>} preferences */
function copilotSection(preferences) {
  let backend = preferences.copilot_backend ?? "claude_code";
  const result = el("div.form-hint.copilot-check");
  const check = () => {
    result.className = "form-hint copilot-check";
    result.textContent = "Checking…";
    checkBackend(backend, true)
      .then((status) => {
        result.classList.add(status.ok ? "ok" : "problem");
        result.textContent = status.message;
      })
      .catch((error) => {
        result.classList.add("problem");
        result.textContent = String(error?.message ?? error);
      });
  };
  const keyInput = /** @type {HTMLInputElement} */ (
    el("input.input", { type: "password", placeholder: "sk-ant-…", autocomplete: "off" })
  );
  const keyRow = el("div.copilot-key", {}, [
    keyInput,
    el("button.button.bordered.small", {
      text: "Keep in the keyring",
      onClick: async () => {
        if (!keyInput.value.trim()) {
          return;
        }
        try {
          await app.api.call("copilot.store_key", { key: keyInput.value.trim() });
          keyInput.value = "";
          check();
        } catch (error) {
          showError("The key could not be kept", error);
        }
      },
    }),
    el("button.button.bordered.small", {
      text: "Remove",
      onClick: async () => {
        try {
          await app.api.call("copilot.delete_key");
          check();
        } catch (error) {
          showError("The key could not be removed", error);
        }
      },
    }),
  ]);
  const choices = BACKENDS.map((choice) => {
    const radio = /** @type {HTMLInputElement} */ (
      el("input", { type: "radio", name: "copilot-backend", value: choice.id, checked: choice.id === backend })
    );
    radio.addEventListener("change", () => {
      backend = choice.id;
      keyRow.hidden = backend !== "api_key";
      result.textContent = "";
    });
    return el("label.form-check.copilot-backend-choice", { title: choice.hint }, [radio, el("span", { text: choice.label })]);
  });
  keyRow.hidden = backend !== "api_key";
  const watchModel = preferences.copilot_watch_model ?? DEFAULT_MODEL;
  const decisionModel = preferences.copilot_decision_model ?? DEFAULT_MODEL;
  const watch = select("copilot-watch-model", withValue(MODELS, watchModel), watchModel);
  const decision = select("copilot-decision-model", withValue(MODELS, decisionModel), decisionModel);
  const effort = select("copilot-effort", EFFORTS, preferences.copilot_effort ?? "low");
  watch.title = "The model of the regular checks";
  decision.title = "The model of events, the start and the end of a run";
  const mode = select("copilot-mode", MODES, preferences.copilot_mode ?? "advisor");
  const level = select("copilot-level", DATA_LEVELS, preferences.copilot_data_level ?? "no_code");
  const calls = /** @type {HTMLInputElement} */ (
    el("input.input", { type: "number", min: 1, step: 1, value: preferences.copilot_max_calls ?? 30 })
  );
  const element = el("div.pref-section", {}, [
    el("div.pref-section-title", { text: "Claude copilot" }),
    row(
      "Connection",
      el("div", {}, [...choices, keyRow, el("button.button.bordered.small", { text: "Check", onClick: check }), result]),
      "How the copilot of a run reaches Claude. Claude Code uses your subscription; nothing switches to the API on its own.",
    ),
    row(
      "Models",
      el("div.copilot-models", {}, [watch, decision, effort]),
      "The first for the regular checks, the second for events, the start and the end of a run; the effort of every call. Low effort answers fastest.",
    ),
    row("New copilot", el("div.copilot-defaults", {}, [mode, level, calls]), "Mode, data sent and calls per run of a copilot you turn on."),
  ]);
  return {
    element,
    values: () => ({
      copilot_backend: backend,
      copilot_watch_model: watch.value || DEFAULT_MODEL,
      copilot_decision_model: decision.value || DEFAULT_MODEL,
      copilot_effort: effort.value,
      copilot_mode: mode.value,
      copilot_data_level: level.value,
      copilot_max_calls: Math.max(1, Math.round(Number(calls.value) || 30)),
    }),
  };
}

export function installCopilotPreferences() {
  preferenceSections.push(copilotSection);
}

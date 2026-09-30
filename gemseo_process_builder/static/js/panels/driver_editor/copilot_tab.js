// @ts-check
// The Copilot tab of an optimization or a DOE: Claude watches the run and helps it
// converge (docs/CLAUDE_PILOT_SPEC.md § 4, § 7, § 10.1).
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { openModal } from "../../components/modal.js";
import { DATA_LEVELS, MODES, actionsFor, copilotSettings, needsConsent } from "../../lib/copilot.js";
import { showPreferences } from "../../shell/preferences_dialog.js";
import { setConfig, tabHeader } from "./common.js";

/**
 * Ask the user before sending data to Claude; remember the answer.
 *
 * @param {string} level - The data level about to be sent.
 * @returns {Promise<boolean>}
 */
export function askConsent(level) {
  const chosen = DATA_LEVELS.find((item) => item.id === level);
  return new Promise((resolve) => {
    openModal({
      title: "Send data to Claude?",
      body: el("div.copilot-consent", {}, [
        el("p", {
          text: "While the run goes on, the copilot sends what it sees of it to Claude, at Anthropic, through Claude Code (your subscription) or your API key, as chosen in the preferences.",
        }),
        el("p", {}, [el("strong", { text: `${chosen?.label}: ` }), chosen?.hint ?? ""]),
        el("p.form-hint", {
          text: "Anthropic's terms and privacy policy apply to what is sent. Nothing is sent before you accept, and you are asked again for a level that sends more.",
        }),
      ]),
      buttons: [
        { label: "Cancel", onClick: () => resolve(false) },
        {
          label: "Accept",
          primary: true,
          onClick: async () => {
            try {
              await app.api.call("prefs.set", { values: { copilot_consent: level } });
            } catch (error) {
              showError("The consent could not be saved", error);
              resolve(false);
              return;
            }
            resolve(true);
          },
        },
      ],
      onClose: () => resolve(false),
    });
  });
}

/**
 * @param {string} name
 * @param {import("../../lib/copilot.js").Choice[]} choices
 * @param {string} value
 */
function choiceSelect(name, choices, value) {
  return /** @type {HTMLSelectElement} */ (
    el(
      "select.input",
      { name },
      choices.map((choice) => el("option", { value: choice.id, text: choice.label, selected: choice.id === value })),
    )
  );
}

/** @param {import("./common.js").TabContext} context */
export function copilotTab(context) {
  const driver = context.driver;
  const intro =
    driver.kind === "doe"
      ? "Claude looks at the samples while they are drawn, explains what they show and places more where they matter."
      : "Claude watches this optimization while it runs, explains what happens and helps it converge.";
  const actions = actionsFor(driver.kind, context.config.formulation?.name ?? "");
  const root = el("div.driver-tab.driver-scroll.copilot-tab", {}, [tabHeader(intro), el("p.placeholder", { text: "Loading…" })]);
  app.api
    .call("prefs.get")
    .then((preferences) =>
      root.replaceChildren(tabHeader(intro), ...copilotForm(driver, actions, driver.config?.copilot, preferences)),
    )
    .catch((error) => showError("The preferences could not be read", error));
  return { element: root };
}

/**
 * @param {any} driver
 * @param {import("../../lib/copilot.js").Choice[]} choices - The actions that apply.
 * @param {Record<string, any> | undefined} stored
 * @param {Record<string, any>} preferences
 */
function copilotForm(driver, choices, stored, preferences) {
  const id = driver.id;
  const settings = copilotSettings(stored, preferences);
  /** @param {Partial<import("../../lib/copilot.js").CopilotSettings>} values */
  const save = (values) => setConfig(id, "copilot", { ...settings, ...values }).catch(() => {});
  /** Whether a level may be sent: asked when it sends more than the accepted one. */
  const allowed = async (/** @type {string} */ level) =>
    !needsConsent(level, preferences.copilot_consent ?? "") || (await askConsent(level));

  const enabled = /** @type {HTMLInputElement} */ (el("input", { type: "checkbox", checked: settings.enabled }));
  enabled.addEventListener("change", async () => {
    if (enabled.checked && !(await allowed(settings.data_level))) {
      enabled.checked = false;
      return;
    }
    save({ enabled: enabled.checked });
  });
  const mode = choiceSelect("mode", MODES, settings.mode);
  mode.addEventListener("change", () => save({ mode: mode.value }));
  const level = choiceSelect("data_level", DATA_LEVELS, settings.data_level);
  level.addEventListener("change", async () => {
    if (settings.enabled && !(await allowed(level.value))) {
      level.value = settings.data_level;
      return;
    }
    save({ data_level: level.value });
  });
  const calls = /** @type {HTMLInputElement} */ (
    el("input.input", { type: "number", min: 1, step: 1, value: settings.max_calls, name: "max_calls" })
  );
  calls.addEventListener("change", () => save({ max_calls: Math.max(1, Math.round(Number(calls.value) || 1)) }));
  const actions = choices.map((action) => {
    const box = /** @type {HTMLInputElement} */ (
      el("input", { type: "checkbox", checked: settings.allowed_actions.includes(action.id), disabled: settings.mode === "observer" })
    );
    box.addEventListener("change", () =>
      save({
        allowed_actions: settings.allowed_actions.filter((item) => item !== action.id).concat(box.checked ? [action.id] : []),
      }),
    );
    return el("label.form-row.form-check", {}, [box, el("span", { text: action.label })]);
  });
  const hint = (/** @type {import("../../lib/copilot.js").Choice[]} */ choices, /** @type {string} */ value) =>
    el("p.form-hint", { text: choices.find((choice) => choice.id === value)?.hint ?? "" });
  const doe = driver.kind === "doe";
  return [
    backendStatus(preferences.copilot_backend ?? "claude_code"),
    el("label.form-row.form-check", {}, [enabled, el("span", { text: `Pilot this ${doe ? "DOE" : "optimization"} with Claude` })]),
    el("fieldset.copilot-settings", { disabled: !settings.enabled }, [
      el("label.form-row", {}, [el("span.form-label", { text: "Mode" }), mode]),
      hint(MODES, settings.mode),
      el("div.form-label", { text: "Claude may" }),
      ...actions,
      el("p.form-hint", {
        text: doe
          ? "Claude draws half of the samples as you set them, then places the others; it never samples beyond your bounds nor draws more samples than you asked."
          : "Whatever it decides, Claude never widens the bounds you set nor spends more evaluations than the maximum of iterations of the algorithm.",
      }),
      el("label.form-row", {}, [el("span.form-label", { text: "Data sent" }), level]),
      hint(DATA_LEVELS, settings.data_level),
      el("label.form-row", { title: "Calls to Claude one run may make" }, [el("span.form-label", { text: "Calls per run" }), calls]),
    ]),
    reviewBox(id, () => allowed(settings.data_level)),
  ];
}

/**
 * *Review with Claude*: a review of the optimization before its run.
 *
 * @param {string} id - The driver.
 * @param {() => Promise<boolean>} allowed - Whether its data may be sent.
 */
function reviewBox(id, allowed) {
  const result = el("div.copilot-review");
  const button = /** @type {HTMLButtonElement} */ (
    el("button.button.bordered", {
      text: "Review with Claude",
      title: "Claude reads the problem and says what to change before running it",
      onClick: async () => {
        if (!(await allowed())) {
          return;
        }
        button.disabled = true;
        result.textContent = "Claude is reviewing the optimization…";
        try {
          const answer = await app.api.call("copilot.review", { driver_id: id }, { timeout: 600_000 });
          result.textContent = answer.text;
        } catch (error) {
          result.textContent = "";
          showError("Claude could not review the optimization", error);
        } finally {
          button.disabled = false;
        }
      },
    })
  );
  return el("div.copilot-review-box", {}, [button, result]);
}

/** @type {Map<string, {time: number, status: Promise<any>}>} */
const checked = new Map();

/** Seconds a check is kept: ``claude auth status`` takes a second or two. */
const CHECK_KEPT_S = 60;

/**
 * The state of a backend, checked by the worker at most once a minute.
 *
 * @param {string} backend
 * @param {boolean} [again] - Check again now.
 * @returns {Promise<{ok: boolean, message: string, installed: boolean}>}
 */
export function checkBackend(backend, again = false) {
  const known = checked.get(backend);
  if (!again && known && performance.now() - known.time < CHECK_KEPT_S * 1000) {
    return known.status;
  }
  const status = app.api.call("copilot.status", { backend }, { timeout: 60_000 });
  status.catch(() => checked.delete(backend));
  checked.set(backend, { time: performance.now(), status });
  return status;
}

/**
 * Whether Claude can be reached with the backend of the preferences.
 *
 * @param {string} backend
 */
function backendStatus(backend) {
  const text = el("span", { text: "Checking the connection to Claude…" });
  const line = el("div.copilot-backend", {}, [
    text,
    el("button.button.bordered.small", { text: "Preferences…", onClick: () => showPreferences() }),
  ]);
  checkBackend(backend)
    .then((status) => {
      line.classList.add(status.ok ? "ok" : "problem");
      text.textContent = status.message;
    })
    .catch((error) => {
      line.classList.add("problem");
      text.textContent = `The connection could not be checked: ${error?.message ?? error}`;
    });
  return line;
}

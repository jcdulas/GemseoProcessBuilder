// @ts-check
// Configuration editors of components, by kind.
import { app } from "../app.js";
import { el } from "../components/dom.js";
import { showError } from "../components/errors.js";
import { formatExpressions, parseExpressionLines } from "../lib/expressions.js";
import { FORMULA_EXAMPLES, FORMULA_FUNCTIONS, FORMULA_OPERATORS, RESERVED_NAMES, complete, completions, formulaSymbols, wordAt } from "../lib/formula_help.js";
import { formatValue, parseValue } from "../lib/table_model.js";
import { openResults } from "../views/results/results_tab.js";
import { openSurrogateWizard } from "../views/surrogate_wizard/wizard.js";
import { openWrapperEditor } from "../views/wrapper_editor/editor.js";
import { disciplineFileSection } from "./discipline_file.js";

const PYTHON_FILTER = "Python files (*.py)";
const TYPING_DELAY_MS = 600;

/** Component kinds whose ports are computed from their configuration. */
export const INTROSPECTED_KINDS = new Set(["analytic", "python_function", "python_class", "executable", "surrogate"]);

/**
 * Replace some configuration values of a component.
 *
 * @param {any} node
 * @param {object} values
 */
function setConfig(node, values) {
  const config = { ...(app.store.node(node.id)?.config ?? {}), ...values };
  return app.store
    .execute({ type: "setNodeProperties", id: node.id, values: { config }, label_text: "Change configuration" })
    .catch((error) => showError("The configuration could not be changed", error));
}

/**
 * @param {string} label
 * @param {Node} control
 * @param {string} [hint]
 */
function row(label, control, hint) {
  return el("div.form-row", {}, [
    el("span.form-label", { text: label }),
    el("div", {}, [control, hint ? el("div.form-hint", { text: hint }) : null]),
  ]);
}

/**
 * A text input committing on change.
 *
 * @param {string} value
 * @param {(value: string) => void} commit
 * @param {string} [placeholder]
 */
function textInput(value, commit, placeholder = "") {
  const input = /** @type {HTMLInputElement} */ (el("input.input.pref-wide", { type: "text", value: value ?? "", placeholder }));
  input.addEventListener("change", () => commit(input.value.trim()));
  return input;
}

/**
 * A module file field with a Browse button.
 *
 * @param {any} node
 */
function moduleFileRow(node) {
  const input = textInput(node.config.module_path ?? "", (value) => setConfig(node, { module_path: value, module: undefined }), "C:\\path\\to\\module.py");
  const browse = el("button.button.bordered", {
    text: "Browse…",
    onClick: async () => {
      const path = await app.api.call("dialog.openFile", { title: "Python module", filter: PYTHON_FILTER });
      if (path) {
        input.value = path;
        setConfig(node, { module_path: path, module: undefined });
      }
    },
  });
  return row("Module file", el("div.input-with-button", {}, [input, browse]), node.config.module ? `Installed module: ${node.config.module}` : undefined);
}

/**
 * An executable wrapper: a reusable descriptor, or a wrapper of its own edited
 * with the wrapper editor.
 *
 * @param {any} node
 */
function executableEditor(node) {
  const input = textInput(node.config.descriptor_path ?? "", (value) => setConfig(node, { descriptor_path: value }), "C:\\path\\to\\wrapper.gpbwrap.json");
  const browse = el("button.button.bordered", {
    text: "Browse…",
    onClick: async () => {
      const path = await app.api.call("dialog.openFile", { title: "Wrapper descriptor", filter: "Wrapper descriptors (*.gpbwrap.json)" });
      if (path) {
        input.value = path;
        setConfig(node, { descriptor_path: path });
      }
    },
  });
  const open = el("button.button.bordered.primary", { text: "Open wrapper editor", onClick: () => openWrapperEditor(node.id) });
  const own = !node.config.descriptor_path && node.config.spec;
  return [
    row("Descriptor", el("div.input-with-button", {}, [input, browse]), own ? `Empty: the wrapper ${node.config.spec.name} of the component.` : "The command, input templates and output rules of the external code."),
    row("Wrapper", open, "Wrap the code graphically from sample input and output files."),
  ];
}

/**
 * A quality value.
 *
 * @param {number | null | undefined} value
 */
function formatQuality(value) {
  return value === null || value === undefined ? "–" : Number(value).toPrecision(3);
}

/**
 * The surrogate of a component: which one, how it was trained and how good it
 * is; retrain it, or build or choose another one.
 *
 * @param {any} node
 */
function surrogateEditor(node) {
  const box = el("div.surrogate-info", {}, [el("div.form-hint", { text: "Reading the surrogates…" })]);
  app.api
    .call("surrogates.list")
    .then((/** @type {any[]} */ entries) => {
      const entry = entries.find((item) => item.id === node.config.surrogate_id);
      const choose = /** @type {HTMLSelectElement} */ (
        el("select.select", {}, [
          el("option", { value: "", text: entries.length ? "Choose a surrogate…" : "No surrogate in the project" }),
          ...entries.map((item) => el("option", { value: item.id, text: item.name + (item.missing ? " (missing)" : "") })),
        ])
      );
      choose.value = entry?.id ?? "";
      choose.addEventListener("change", () => {
        if (choose.value) {
          app.api.call("surrogates.use", { node: node.id, id: choose.value }).catch((error) => showError("The surrogate could not be used", error));
        }
      });
      const build = el("button.button.bordered", { text: "Build surrogate…", onClick: () => openSurrogateWizard({ nodeId: node.id }) });
      /** @type {(Node | null)[]} */
      const parts = [row("Surrogate", choose), el("div.inspector-actions", {}, [build])];
      const metadata = entry?.metadata;
      if (metadata) {
        const source = metadata.source;
        const quality = Object.entries(metadata.quality).map(([name, values]) =>
          el("div", { text: `${name}: R² ${formatQuality(/** @type {any} */ (values).r2_cv?.[0])} (cross-validation), ${formatQuality(/** @type {any} */ (values).r2?.[0])} (training)` }),
        );
        parts.push(
          row("Model", el("span", { text: metadata.algorithm })),
          row("Trained on", el("span", { text: `${metadata.n_samples} samples of ${source.name || source.id}${source.deleted ? " (run deleted)" : ""}` })),
          row("Updated", el("span", { text: metadata.updated.replace("T", " ").slice(0, 16) })),
          row("Quality", el("div", {}, quality)),
          el("div.inspector-actions", {}, [
            el("button.button.bordered", { text: "Retrain…", title: "Train it again, with other settings or another run", onClick: () => openSurrogateWizard({ nodeId: node.id, retrain: entry }) }),
            source.deleted ? null : el("button.button.bordered", { text: "Show source run", onClick: () => openResults(source.id) }),
          ]),
        );
      } else if (node.config.model_path) {
        parts.push(el("div.form-error", { text: `The surrogate ${node.config.model_path} is not in the project.` }));
      }
      box.replaceChildren(...parts);
    })
    .catch((error) => box.replaceChildren(el("div.form-error", { text: error.message })));
  return [box];
}

/**
 * The names of the variables of the other components: typing one of them in a
 * formula couples the components.
 *
 * @param {string} nodeId
 */
function modelVariables(nodeId) {
  const names = new Set();
  for (const other of Object.values(app.store.state.nodes)) {
    if (other.id !== nodeId) {
      for (const port of other.ports ?? []) {
        names.add(port.local_name ?? port.name);
      }
    }
  }
  return [...names].filter((name) => name && !RESERVED_NAMES.has(name)).sort();
}

/**
 * Insert a text at the caret of a text area, as if typed.
 *
 * @param {HTMLTextAreaElement} area
 * @param {string} text
 * @param {number} [caretOffset] - Where the caret goes in the inserted text.
 */
function insertAtCaret(area, text, caretOffset = text.length) {
  const start = area.selectionStart ?? area.value.length;
  area.setRangeText(text, start, area.selectionEnd ?? start, "end");
  area.selectionStart = area.selectionEnd = start + caretOffset;
  area.focus();
  area.dispatchEvent(new Event("input"));
}

/** @param {any} node */
function analyticEditor(node) {
  const area = /** @type {HTMLTextAreaElement} */ (
    el("textarea.input.form-textarea.expressions", { rows: 4, spellcheck: "false", placeholder: "y = x**2 + sin(z)" })
  );
  area.value = formatExpressions(node.config.expressions);
  const errors = el("div.form-error");
  const summary = el("div.formula-summary");
  const suggestions = el("div.formula-suggestions");
  const examples = el("div.formula-examples");
  const variables = modelVariables(node.id);
  /** @type {{name: string, insert: string, help: string}[]} */
  let offered = [];
  /** @type {any} */
  let timer = null;

  const commit = () => {
    const { expressions, errors: problems } = parseExpressionLines(area.value);
    errors.textContent = problems.join(" ");
    if (!problems.length && JSON.stringify(expressions) !== JSON.stringify(app.store.node(node.id)?.config.expressions ?? {})) {
      setConfig(node, { expressions });
    }
  };

  /** What the formulas define, and the names SymPy would misread. */
  const renderSummary = () => {
    const { expressions } = parseExpressionLines(area.value);
    const symbols = formulaSymbols(expressions);
    const list = (/** @type {string} */ label, /** @type {string[]} */ names) =>
      el("span.formula-names", {}, [el("span.form-hint", { text: `${label}: ` }), names.length ? names.join(", ") : "none"]);
    summary.replaceChildren(
      ...(symbols.outputs.length ? [list("Inputs", symbols.inputs), list("Outputs", symbols.outputs)] : []),
      ...symbols.reserved.map((name) =>
        el("div.form-error", { text: `SymPy reads ${name} as a function or a constant: rename it (${name}_1, for example).` }),
      ),
    );
    examples.hidden = area.value.trim() !== "";
  };

  /** Complete the word being typed: the variables of the model, then the functions. */
  const renderSuggestions = () => {
    const word = document.activeElement === area ? wordAt(area.value, area.selectionStart ?? 0) : null;
    offered = word ? completions(word.word, variables) : [];
    suggestions.replaceChildren(
      ...offered.map((item, index) =>
        el(`button.formula-chip${index === 0 ? ".first" : ""}`, {
          text: item.insert.replace("(, )", "( , )"),
          title: `${item.help}${index === 0 ? " (Tab)" : ""}`,
          onMousedown: (/** @type {MouseEvent} */ event) => event.preventDefault(),
          onClick: () => accept(item),
        }),
      ),
    );
    suggestions.hidden = !offered.length;
  };

  /** @param {{insert: string}} item */
  const accept = (item) => {
    const word = wordAt(area.value, area.selectionStart ?? 0);
    if (!word) {
      return;
    }
    const next = complete(area.value, word, item.insert);
    area.value = next.text;
    area.selectionStart = area.selectionEnd = next.caret;
    area.dispatchEvent(new Event("input"));
  };

  area.addEventListener("input", () => {
    renderSummary();
    renderSuggestions();
    clearTimeout(timer);
    timer = setTimeout(commit, TYPING_DELAY_MS);
  });
  area.addEventListener("keydown", (event) => {
    if (event.key === "Tab" && offered.length && !event.shiftKey) {
      event.preventDefault();
      accept(offered[0]);
    } else if (event.key === "Escape" && offered.length) {
      offered = [];
      suggestions.hidden = true;
    }
  });
  area.addEventListener("click", renderSuggestions);
  area.addEventListener("blur", () => {
    clearTimeout(timer);
    suggestions.hidden = true;
    commit();
  });

  // Examples while the component has no formula.
  examples.replaceChildren(
    el("div.form-hint", { text: "Start from an example (click to use it):" }),
    ...FORMULA_EXAMPLES.map((example) =>
      el("button.formula-chip", { text: example.text, title: example.help, onClick: () => insertAtCaret(area, `${example.text}\n`) }),
    ),
  );
  // The functions, the operators and the variables of the model, to insert.
  const help = el("details.formula-help", {}, [
    el("summary", { text: "Functions, operators and variables" }),
    el("div.form-hint", { text: "Click to insert at the cursor. While typing, Tab completes the first suggestion." }),
    el("div.formula-chips", {}, [
      ...FORMULA_FUNCTIONS.map((item) =>
        el("button.formula-chip", { text: item.name, title: item.help, onClick: () => insertAtCaret(area, item.insert, item.insert.indexOf("(") + 1) }),
      ),
    ]),
    el(
      "ul.formula-operators",
      {},
      FORMULA_OPERATORS.map((item) => el("li", {}, [el("code", { text: item.text }), ` ${item.help}`])),
    ),
    variables.length
      ? el("div", {}, [
          el("div.form-hint", { text: "Variables of the other components: using one couples this component with them." }),
          el(
            "div.formula-chips",
            {},
            variables.slice(0, 40).map((name) => el("button.formula-chip.variable", { text: name, onClick: () => insertAtCaret(area, name) })),
          ),
        ])
      : null,
  ]);
  renderSummary();
  suggestions.hidden = true;
  // Full width: the formulas need room, and the hint comes before them.
  return [
    el("div.form-block", {}, [
      el("span.form-label", { text: "Formulas" }),
      el("div.form-hint", { text: "One formula per line, like y = 2*x + 1: the name before = is an output, the other names are inputs." }),
      area,
      suggestions,
      errors,
      summary,
      examples,
      help,
    ]),
  ];
}

/** @param {any} node */
function functionEditor(node) {
  return [
    moduleFileRow(node),
    row("Function", textInput(node.config.function ?? "", (value) => setConfig(node, { function: value }))),
  ];
}

/** @param {any} node */
function classEditor(node) {
  const argumentsBox = el("div.init-args", {}, [el("span.form-hint", { text: "Loading the constructor parameters…" })]);
  const load = async () => {
    if (!node.config.class || !(node.config.module_path || node.config.module)) {
      argumentsBox.replaceChildren(el("span.form-hint", { text: "Select a module and a class." }));
      return;
    }
    let parameters;
    try {
      parameters = await app.api.call("component.initSignature", { config: node.config }, { timeout: 90000 });
    } catch (error) {
      argumentsBox.replaceChildren(el("span.form-error", { text: /** @type {any} */ (error).message }));
      return;
    }
    if (!parameters.length) {
      argumentsBox.replaceChildren(el("span.form-hint", { text: "The constructor has no parameters." }));
      return;
    }
    const current = node.config.init_args ?? {};
    argumentsBox.replaceChildren(
      ...parameters.map((/** @type {any} */ parameter) => {
        const input = /** @type {HTMLInputElement} */ (
          el("input.input.pref-wide", {
            type: "text",
            value: parameter.name in current ? formatValue(current[parameter.name]) : "",
            placeholder: parameter.required ? "required" : `default: ${formatValue(parameter.default)}`,
          })
        );
        input.addEventListener("change", () => {
          const args = { ...(app.store.node(node.id)?.config.init_args ?? {}) };
          const parsed = parseValue(input.value);
          if (parsed.value === null) {
            delete args[parameter.name];
          } else {
            args[parameter.name] = parsed.value;
          }
          setConfig(node, { init_args: args });
        });
        return row(`${parameter.name}${parameter.annotation ? ` (${parameter.annotation})` : ""}`, input);
      }),
    );
  };
  load();
  return [
    disciplineFileSection(node),
    moduleFileRow(node),
    row("Class", textInput(node.config.class ?? "", (value) => setConfig(node, { class: value }))),
    el("div.form-subtitle", { text: "Constructor arguments" }),
    argumentsBox,
  ];
}

/**
 * The configuration section of a component, or null for kinds edited elsewhere.
 *
 * @param {any} node
 * @returns {HTMLElement | null}
 */
export function componentConfigSection(node) {
  const editors = {
    analytic: analyticEditor,
    python_function: functionEditor,
    python_class: classEditor,
    executable: executableEditor,
    surrogate: surrogateEditor,
  };
  const editor = editors[/** @type {keyof editors} */ (node.kind)];
  if (!editor) {
    return null;
  }
  const status = el("div.component-status");
  const showStatus = () => {
    const { state, error } = app.componentStatus.get(node.id);
    status.className = `component-status status-${state}`;
    status.textContent = state === "running" ? "Reading the variables…" : state === "error" ? error : "";
  };
  showStatus();
  const stop = app.componentStatus.onChange((id) => {
    if (!status.isConnected) {
      stop();
    } else if (id === node.id) {
      showStatus();
    }
  });
  return el("div.inspector-section", {}, [
    el("div.section-header", {}, [
      el("h3.section-title", { text: "Configuration" }),
      el("button.button.bordered", {
        text: "Re-read variables",
        title: "Import the component again and update its variables",
        onClick: () => app.api.call("component.introspect", { id: node.id }),
      }),
    ]),
    ...editor(node),
    status,
  ]);
}

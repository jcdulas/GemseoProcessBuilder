// @ts-check
// The Outputs tab of the wrapper editor: the rules reading the outputs.
//
// The user loads a sample output file (or the standard output of the code) and
// selects a value, or a column of values: rules reading it are suggested, each
// previewed on the sample by runtime/parsing.py, and only those reading the
// selected value are offered.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { openModal } from "../../components/modal.js";
import { numberAt, numberTokens } from "../../lib/number_selection.js";
import { sameValue, suggestRules } from "../../lib/rule_suggestion.js";
import { button, parseNumberInput, row, selectInput, textInput } from "./fields.js";
import { TextView } from "./text_view.js";

const STDOUT = "stdout";

/** The fields of each kind of rule, with their labels. */
const RULE_FIELDS = {
  key_value: [
    ["key", "Key"],
    ["separator", "Separator"],
  ],
  marker: [
    ["marker", "Marker"],
    ["line", "Line after the marker"],
    ["column", "Column"],
  ],
  table: [
    ["marker", "Marker"],
    ["column", "Column"],
    ["skip", "Header lines"],
    ["end", "End line"],
  ],
  regex: [
    ["pattern", "Pattern"],
    ["group", "Group"],
    ["occurrence", "Occurrence"],
  ],
  file: [],
};
const NUMERIC_FIELDS = new Set(["line", "column", "skip", "group"]);

/** A short description of a rule. */
export function describeRule(rule) {
  switch (rule.kind) {
    case "key_value":
      return `${rule.key} ${rule.separator ?? "="} value`;
    case "marker":
      return `"${rule.marker}", line +${rule.line ?? 1}, column ${rule.column ?? 0}`;
    case "table":
      return `Table after "${rule.marker}", column ${rule.column ?? 0}`;
    case "regex":
      return `/${rule.pattern}/${rule.occurrence && rule.occurrence !== "first" ? ` (${rule.occurrence})` : ""}`;
    default:
      return "Path of the file";
  }
}

/** @param {any} value */
function formatRead(value) {
  if (Array.isArray(value)) {
    return value.length > 4 ? `[${value.slice(0, 4).join(", ")}, …] (${value.length})` : `[${value.join(", ")}]`;
  }
  return String(value);
}

export class OutputsTab {
  /**
   * @param {HTMLElement} page
   * @param {import("./editor.js").WrapperEditor} editor
   */
  constructor(page, editor) {
    this.page = page;
    this.editor = editor;
    /** The file of the sample shown. */
    this.file = "";
    /** Counters dropping the answers of outdated previews. */
    this.selectionToken = 0;
    this.rulesToken = 0;
    this.toolbar = el("div.results-toolbar");
    this.suggestions = el("div.wrapper-selection");
    const textBox = el("div.wrapper-text-box");
    this.textView = new TextView(textBox, {
      placeholder: "Load a sample output file of the code (or its standard output), then select the values to read.",
      onSelect: (selection) => this.onSelect(selection),
    });
    this.rules = el("div.wrapper-side");
    page.replaceChildren(this.toolbar, el("div.wrapper-split", {}, [el("div.wrapper-main", {}, [this.suggestions, textBox]), this.rules]));
  }

  get samples() {
    return this.editor.outputSamples;
  }

  render() {
    const files = Object.keys(this.samples);
    if (!files.includes(this.file)) {
      this.file = files[0] ?? "";
    }
    const items = [el("span", { text: "Sample" })];
    if (files.length) {
      items.push(
        selectInput(
          this.file,
          files.map((file) => [file, file]),
          (value) => {
            this.file = value;
            this.render();
          },
        ),
        el("span", { text: "read as", title: "The file of the working folder the rules read" }),
        textInput(this.file, (value) => this.renameSample(value.trim())),
      );
    }
    items.push(
      button("Load sample…", () => this.loadSample(), { title: "Read a sample output file of the code" }),
      button("Add file output…", () => this.addFileOutput(), { title: "An output giving the path of a file produced by the code" }),
    );
    this.toolbar.replaceChildren(...items);
    this.textView.setText(this.samples[this.file] ?? "");
    this.suggestions.replaceChildren(el("span.form-hint", { text: this.file ? "Select a value, or a column of values on several lines." : "" }));
    this.renderRules();
  }

  async loadSample() {
    const path = await app.api.call("dialog.openFile", { title: "Sample output file" });
    if (!path) {
      return;
    }
    try {
      const { name, text, truncated } = await app.api.call("executable.readSample", { path });
      if (truncated) {
        showError("Large file", new Error(`${name} is larger than 5 MB: only its beginning is loaded.`));
      }
      this.samples[name] = text;
      this.file = name;
      this.render();
    } catch (error) {
      showError("The sample could not be read", error);
    }
  }

  /**
   * Read the sample as another file of the working folder ("stdout" for the
   * standard output); the rules of the old name follow.
   *
   * @param {string} name
   */
  renameSample(name) {
    if (!name || name === this.file || this.samples[name] !== undefined) {
      return;
    }
    this.samples[name] = this.samples[this.file];
    delete this.samples[this.file];
    for (const rule of this.editor.spec.rules ?? []) {
      if ((rule.file ?? STDOUT) === this.file) {
        rule.file = name;
      }
    }
    this.file = name;
    this.editor.changed();
  }

  /** @param {{start: number, end: number}} selection */
  async onSelect(selection) {
    const text = this.textView.text;
    let { start, end } = selection;
    if (start === end) {
      const token = numberAt(text, start);
      if (!token) {
        return;
      }
      ({ start, end } = token);
      this.textView.select(start, end);
    }
    const tokens = numberTokens(text).filter((token) => token.end > start && token.start < end);
    if (!tokens.length) {
      this.suggestions.replaceChildren(el("span.form-hint", { text: "The selection holds no number." }));
      return;
    }
    const multiline = text.slice(start, end).includes("\n");
    const expected = multiline ? tokens.map((token) => token.value) : tokens[0].value;
    const suggestions = suggestRules(text, start, end);
    const token = ++this.selectionToken;
    const previews = await Promise.all(
      suggestions.map(({ rule }) => app.api.call("executable.preview", { rule: { variable: "value", file: this.file, ...rule }, text }).catch((error) => ({ value: null, error: error.message }))),
    );
    if (token !== this.selectionToken) {
      return;
    }
    const valid = suggestions.filter((_, index) => !previews[index].error && sameValue(previews[index].value, expected));
    this.showSuggestions(valid, expected, text.slice(0, start));
  }

  /**
   * @param {{label: string, rule: any}[]} suggestions
   * @param {number | number[]} expected
   * @param {string} before - The text before the value, for a name.
   */
  showSuggestions(suggestions, expected, before) {
    if (!suggestions.length) {
      this.suggestions.replaceChildren(el("span.form-hint", { text: "No rule reads this value: write one with Add rule." }), button("Add rule…", () => this.editRule(null)));
      return;
    }
    const outputs = this.editor.spec.outputs ?? [];
    const label = before.split("\n").pop()?.replace(/[=:]\s*$/, "").trim().split(/\s+/).pop() ?? "";
    const guessed = /^[A-Za-z_]\w*$/.test(label) && !outputs.some((/** @type {any} */ port) => port.name === label) ? label : `y_${outputs.length + 1}`;
    const name = textInput(guessed, () => {});
    const choice = selectInput(
      "0",
      suggestions.map((suggestion, index) => [String(index), suggestion.label]),
      () => {},
    );
    this.suggestions.replaceChildren(
      el("span", { text: `Read ${formatRead(expected)} as` }),
      name,
      el("span", { text: "with" }),
      choice,
      button(
        "Add output",
        () => {
          const variable = name.value.trim();
          if (!/^[A-Za-z_][\w.-]*$/.test(variable)) {
            name.classList.add("invalid");
            return;
          }
          const { rule } = suggestions[Number(choice.value)];
          this.addOutput(variable, { ...rule, variable, file: this.file }, Array.isArray(expected) ? expected.length : 1);
        },
        { primary: true },
      ),
    );
  }

  /**
   * Add an output and its rule (or replace the rule of an output).
   *
   * @param {string} name
   * @param {any} rule
   * @param {number} size
   */
  addOutput(name, rule, size) {
    const spec = this.editor.spec;
    spec.outputs ??= [];
    spec.rules ??= [];
    const port = spec.outputs.find((/** @type {any} */ item) => item.name === name);
    if (port) {
      port.size = size;
    } else {
      spec.outputs.push({ name, size });
    }
    const output = spec.outputs.find((/** @type {any} */ item) => item.name === name);
    if (output.size === 1) {
      delete output.size;
    }
    if (rule.file === STDOUT) {
      delete rule.file;
    }
    spec.rules = [...spec.rules.filter((/** @type {any} */ item) => item.variable !== name), rule];
    this.editor.changed();
  }

  addFileOutput() {
    const name = textInput("result_file", () => {});
    const file = textInput("", () => {}, { placeholder: "result.csv" });
    openModal({
      title: "Add a file output",
      body: el("div.wrapper-form", {}, [row("Output", name), row("File", file, "The file of the working folder; the output is its path.")]),
      buttons: [
        { label: "Cancel" },
        {
          label: "Add output",
          primary: true,
          onClick: () => {
            if (!name.value.trim() || !file.value.trim()) {
              return false;
            }
            this.addOutput(name.value.trim(), { kind: "file", variable: name.value.trim(), file: file.value.trim() }, 1);
            this.editor.spec.outputs.find((/** @type {any} */ port) => port.name === name.value.trim()).dtype = "path";
          },
        },
      ],
    });
  }

  /**
   * Edit a rule field by field (or write a new one).
   *
   * @param {any} rule
   */
  editRule(rule) {
    const edited = rule ? { ...rule } : { kind: "regex", variable: `y_${(this.editor.spec.outputs ?? []).length + 1}`, file: this.file, pattern: "" };
    const fields = el("div");
    const preview = el("div.form-hint");
    const refresh = async () => {
      const text = this.samples[edited.file ?? STDOUT];
      if (text === undefined) {
        preview.textContent = "Load a sample of this file to preview the rule.";
        return;
      }
      const { value, error } = await app.api.call("executable.preview", { rule: edited, text });
      preview.textContent = error || `Reads ${formatRead(value)}`;
    };
    const renderFields = () => {
      const kinds = /** @type {[string, string][]} */ (Object.keys(RULE_FIELDS).map((kind) => [kind, kind]));
      fields.replaceChildren(
        row("Output", textInput(edited.variable, (value) => (edited.variable = value.trim()))),
        row("File", textInput(edited.file ?? STDOUT, (value) => ((edited.file = value.trim() || STDOUT), refresh()))),
        row(
          "Kind",
          selectInput(edited.kind, kinds, (value) => {
            edited.kind = value;
            renderFields();
            refresh();
          }),
        ),
        ...RULE_FIELDS[/** @type {keyof RULE_FIELDS} */ (edited.kind)].map(([key, label]) =>
          row(
            label,
            textInput(edited[key] === undefined ? "" : String(edited[key]), (value) => {
              if (value === "") {
                delete edited[key];
              } else {
                edited[key] = NUMERIC_FIELDS.has(key) ? parseNumberInput(value, 0) : value;
              }
              refresh();
            }),
          ),
        ),
      );
    };
    renderFields();
    refresh();
    openModal({
      title: rule ? `Rule of ${rule.variable}` : "Add a rule",
      body: el("div.wrapper-form", {}, [fields, preview]),
      buttons: [
        { label: "Cancel" },
        {
          label: "Save rule",
          primary: true,
          onClick: () => {
            if (!edited.variable) {
              return false;
            }
            const spec = this.editor.spec;
            if (rule && rule.variable !== edited.variable) {
              const port = (spec.outputs ?? []).find((/** @type {any} */ item) => item.name === rule.variable);
              if (port) {
                port.name = edited.variable;
              }
            }
            spec.rules = (spec.rules ?? []).filter((/** @type {any} */ item) => item !== rule);
            this.addOutput(edited.variable, edited, (spec.outputs ?? []).find((/** @type {any} */ item) => item.name === edited.variable)?.size ?? 1);
          },
        },
      ],
    });
  }

  /** The outputs with their rules and the values they read in the samples. */
  async renderRules() {
    const spec = this.editor.spec;
    const outputs = spec.outputs ?? [];
    const rules = spec.rules ?? [];
    const token = ++this.rulesToken;
    const previews = await Promise.all(
      rules.map((/** @type {any} */ rule) => {
        const text = this.samples[rule.file ?? STDOUT];
        if (text === undefined || rule.kind === "file") {
          return { value: null, error: "", missing: true };
        }
        return app.api.call("executable.preview", { rule, text }).catch((error) => ({ value: null, error: error.message }));
      }),
    );
    if (token !== this.rulesToken) {
      return;
    }
    const rows = outputs.map((/** @type {any} */ port, /** @type {number} */ index) => {
      const ruleIndex = rules.findIndex((/** @type {any} */ rule) => rule.variable === port.name);
      const rule = rules[ruleIndex];
      const read = previews[ruleIndex];
      const status = !rule ? "No rule" : read.missing ? "" : read.error ? read.error : formatRead(read.value);
      return el("tr", {}, [
        el("td", {}, [
          textInput(port.name, (value) => {
            const name = value.trim();
            if (rule) {
              rule.variable = name;
            }
            port.name = name;
            this.editor.changed();
          }),
        ]),
        el("td", {}, [
          textInput(port.unit ?? "", (value) => {
            port.unit = value.trim() || undefined;
            this.editor.changed();
          }),
        ]),
        el("td.wrapper-rule", { text: rule ? `${rule.file ?? STDOUT}: ${describeRule(rule)}` : "", title: rule ? describeRule(rule) : "" }),
        el(`td.wrapper-preview${read?.error || !rule ? ".invalid" : ""}`, { text: status, title: status }),
        el("td", {}, [
          rule ? button("Edit…", () => this.editRule(rule)) : button("Add rule…", () => this.editRule({ kind: "regex", variable: port.name, file: this.file || STDOUT, pattern: "" })),
          button("×", () => {
            outputs.splice(index, 1);
            spec.rules = rules.filter((/** @type {any} */ item) => item.variable !== port.name);
            this.editor.changed();
          }, { title: "Remove the output and its rule" }),
        ]),
      ]);
    });
    this.rules.replaceChildren(
      el("h3.section-title", { text: `Outputs (${outputs.length})` }),
      el("table.wrapper-table", {}, [el("tr", {}, ["Name", "Unit", "Rule", "Sample value", ""].map((title) => el("th", { text: title }))), ...rows]),
      button("Add rule…", () => this.editRule(null)),
    );
  }
}


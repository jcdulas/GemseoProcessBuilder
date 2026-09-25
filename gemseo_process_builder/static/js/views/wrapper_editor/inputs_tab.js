// @ts-check
// The Inputs tab of the wrapper editor: input files written from templates.
//
// The user loads a sample input file, then selects the numbers the inputs
// replace: each selection becomes a {{name:format}} marker, and the input is
// declared with the selected value as its default.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { askConfirmation, openModal } from "../../components/modal.js";
import { markerValueText, numberAt, renameMarkers, replaceByMarker, selectionNumbers, templateMarkers } from "../../lib/number_selection.js";
import { button, formatValueInput, parseValueInput, row, selectInput, textInput } from "./fields.js";
import { TextView } from "./text_view.js";

const DTYPES = /** @type {[string, string][]} */ ([
  ["float", "float"],
  ["int", "int"],
  ["str", "str"],
  ["path", "path"],
]);

/** The last part of a path. */
export function baseName(path) {
  return path.split(/[\\/]/).pop() ?? path;
}

export class InputsTab {
  /**
   * @param {HTMLElement} page
   * @param {import("./editor.js").WrapperEditor} editor
   */
  constructor(page, editor) {
    this.page = page;
    this.editor = editor;
    /** The template shown. */
    this.index = 0;
    this.editing = false;
    /** @type {{start: number, end: number} | null} */
    this.selected = null;

    this.toolbar = el("div.results-toolbar");
    this.selectionBar = el("div.wrapper-selection");
    const textBox = el("div.wrapper-text-box");
    this.textView = new TextView(textBox, {
      placeholder: "Load a sample input file of the code, then select the values the inputs replace.",
      onSelect: (selection) => this.onSelect(selection),
    });
    this.area = /** @type {HTMLTextAreaElement} */ (el("textarea.input.wrapper-text-area", { spellcheck: "false" }));
    this.area.addEventListener("change", () => {
      const template = this.template;
      if (template) {
        template.content = this.area.value;
        this.editor.changed();
      }
    });
    textBox.append(this.area);
    this.ports = el("div.wrapper-side");
    page.replaceChildren(this.toolbar, el("div.wrapper-split", {}, [el("div.wrapper-main", {}, [this.selectionBar, textBox]), this.ports]));
  }

  get templates() {
    const spec = this.editor.spec;
    spec.templates ??= [];
    return spec.templates;
  }

  get template() {
    return this.templates[this.index] ?? null;
  }

  render() {
    this.index = Math.min(this.index, Math.max(0, this.templates.length - 1));
    this.renderToolbar();
    const template = this.template;
    const text = template?.content ?? "";
    this.textView.root.hidden = this.editing;
    this.area.hidden = !this.editing;
    if (this.editing) {
      this.area.value = text;
    } else {
      const names = new Set((this.editor.spec.inputs ?? []).map((/** @type {any} */ port) => port.name));
      this.textView.setText(
        text,
        templateMarkers(text).map((marker) => ({
          start: marker.start,
          end: marker.end,
          className: names.has(marker.name) ? "wrapper-marker" : "wrapper-marker.unknown",
          title: names.has(marker.name) ? `Input ${marker.name}` : `${marker.name} is not an input`,
        })),
      );
    }
    this.selected = null;
    this.renderSelection();
    this.renderPorts();
  }

  renderToolbar() {
    const templates = this.templates;
    /** @type {HTMLElement[]} */
    const items = [el("span", { text: "Input file" })];
    if (templates.length) {
      items.push(
        selectInput(
          String(this.index),
          templates.map((/** @type {any} */ template, /** @type {number} */ index) => [String(index), template.target]),
          (value) => {
            this.index = Number(value);
            this.render();
          },
        ),
        textInput(this.template.target, (value) => {
          if (value.trim()) {
            this.template.target = value.trim();
            this.editor.changed();
          }
        }),
      );
    }
    items.push(button("Load sample…", () => this.loadSample(), { title: "Read a sample input file of the code" }));
    if (templates.length) {
      items.push(
        button("Add file…", () => this.loadSample(true), { title: "Another input file" }),
        button(this.editing ? "Done" : "Edit text", () => {
          this.editing = !this.editing;
          this.render();
        }),
        button("Remove file", () => this.removeTemplate()),
      );
    }
    this.toolbar.replaceChildren(...items);
  }

  /**
   * Read a sample input file: it replaces the file shown, or is added.
   *
   * @param {boolean} [added]
   */
  async loadSample(added = !this.templates.length) {
    const path = await app.api.call("dialog.openFile", { title: "Sample input file" });
    if (!path) {
      return;
    }
    try {
      const { name, text, truncated } = await app.api.call("executable.readSample", { path });
      if (truncated) {
        showError("Large file", new Error(`${name} is larger than 5 MB: only its beginning is loaded.`));
      }
      if (added) {
        this.templates.push({ target: name, content: text });
        this.index = this.templates.length - 1;
      } else {
        const template = this.template;
        if (templateMarkers(template.content ?? "").length && !(await askConfirmation("Replace the input file", `Replace ${template.target} and its markers?`, "Replace"))) {
          return;
        }
        template.content = text;
      }
      this.editor.changed();
    } catch (error) {
      showError("The sample could not be read", error);
    }
  }

  async removeTemplate() {
    const template = this.template;
    if (await askConfirmation("Remove the input file", `Stop writing ${template.target}?`, "Remove")) {
      this.templates.splice(this.index, 1);
      this.editor.changed();
    }
  }

  /** @param {{start: number, end: number}} selection */
  onSelect(selection) {
    const text = this.textView.text;
    let { start, end } = selection;
    const marker = templateMarkers(text).find((item) => item.start <= start && start < item.end);
    if (marker) {
      this.selected = { start: marker.start, end: marker.end };
    } else {
      if (start === end) {
        // A click selects the number under it.
        const token = numberAt(text, start);
        if (!token) {
          this.selected = null;
          this.renderSelection();
          return;
        }
        ({ start, end } = token);
        this.textView.select(start, end);
      }
      this.selected = { start, end };
    }
    this.renderSelection();
  }

  renderSelection() {
    const text = this.textView.text;
    const selected = this.selected;
    if (!selected || this.editing) {
      this.selectionBar.replaceChildren(el("span.form-hint", { text: this.template ? "Select a value, or a vector of values, to make it an input." : "" }));
      return;
    }
    const marker = templateMarkers(text).find((item) => item.start === selected.start && item.end === selected.end);
    if (marker) {
      this.selectionBar.replaceChildren(
        el("span", { text: `Marker of ${marker.name}${marker.format ? ` written as ${marker.format}` : ""}` }),
        button("Remove marker", () => this.removeMarker(marker)),
      );
      return;
    }
    const found = selectionNumbers(text.slice(selected.start, selected.end));
    if (!found) {
      this.selectionBar.replaceChildren(el("span.form-hint", { text: "The selection is not a number or a vector of numbers." }));
      return;
    }
    const values = found.values.length > 4 ? `${found.values.slice(0, 4).join(", ")}, … (${found.values.length} values)` : found.values.join(", ");
    this.selectionBar.replaceChildren(el("span", { text: `Selected: ${values}` }), button("Make variable…", () => this.makeVariable(found), { primary: true }));
  }

  /**
   * Replace the selection by the marker of an input.
   *
   * @param {{values: number[], separator: string, format: string}} found
   */
  makeVariable(found) {
    const inputs = this.editor.spec.inputs ?? [];
    const name = textInput(`x_${inputs.length + 1}`, () => {});
    const format = textInput(found.format, () => {});
    const unit = textInput("", () => {}, { placeholder: "m, kg/s, …" });
    const description = textInput("", () => {});
    const body = el("div.wrapper-form", {}, [
      row("Name", name),
      row("Format", format, "A Python format: .6e, 12.4f, .0f… Empty: the value as it is."),
      row("Unit", unit),
      row("Description", description),
    ]);
    openModal({
      title: found.values.length > 1 ? `Make a vector of ${found.values.length} values` : "Make a variable",
      body,
      buttons: [
        { label: "Cancel" },
        {
          label: "Make variable",
          primary: true,
          onClick: () => {
            const variable = name.value.trim();
            if (!/^[A-Za-z_][\w.-]*$/.test(variable)) {
              name.classList.add("invalid");
              return false;
            }
            this.addMarker(variable, format.value.trim(), unit.value.trim(), description.value.trim(), found.separator);
          },
        },
      ],
    });
    name.select();
  }

  /**
   * @param {string} name
   * @param {string} format
   * @param {string} unit
   * @param {string} description
   * @param {string} separator
   */
  addMarker(name, format, unit, description, separator) {
    const selected = /** @type {{start: number, end: number}} */ (this.selected);
    const template = this.template;
    const result = replaceByMarker(template.content, selected.start, selected.end, name, { format });
    if (!result) {
      return;
    }
    template.content = result.text;
    const spec = this.editor.spec;
    spec.inputs ??= [];
    const existing = spec.inputs.find((/** @type {any} */ port) => port.name === name);
    const port = existing ?? { name };
    Object.assign(port, { size: result.port.size, default: result.port.default });
    if (port.size === 1) {
      delete port.size;
    }
    if (unit) {
      port.unit = unit;
    }
    if (description) {
      port.description = description;
    }
    if (!existing) {
      spec.inputs.push(port);
    }
    if (result.port.size > 1 && separator !== " ") {
      spec.vector_separator = separator;
    }
    this.editor.changed();
  }

  /** @param {{start: number, end: number, name: string, format: string}} marker */
  removeMarker(marker) {
    const template = this.template;
    const port = (this.editor.spec.inputs ?? []).find((/** @type {any} */ item) => item.name === marker.name);
    const text = markerValueText(port?.default ?? 0, marker.format, this.editor.spec.vector_separator ?? " ");
    template.content = template.content.slice(0, marker.start) + text + template.content.slice(marker.end);
    this.editor.changed();
  }

  /** The inputs, editable, with the files using them. */
  renderPorts() {
    const spec = this.editor.spec;
    const inputs = spec.inputs ?? [];
    const used = new Set(this.templates.flatMap((/** @type {any} */ template) => templateMarkers(template.content ?? "").map((marker) => marker.name)));
    const rows = inputs.map((/** @type {any} */ port, /** @type {number} */ index) =>
      el("tr", {}, [
        el("td", {}, [
          textInput(port.name, (value) => {
            const name = value.trim();
            for (const template of this.templates) {
              template.content = renameMarkers(template.content ?? "", port.name, name);
            }
            port.name = name;
            this.editor.changed();
          }),
        ]),
        el("td", {}, [
          selectInput(port.dtype ?? "float", DTYPES, (value) => {
            port.dtype = value;
            if (value === "float") {
              delete port.dtype;
            }
            this.editor.changed();
          }),
        ]),
        el("td", {}, [
          textInput(formatValueInput(port.default), (value) => {
            const parsed = parseValueInput(value);
            port.default = parsed;
            port.size = Array.isArray(parsed) ? parsed.length : 1;
            if (port.size === 1) {
              delete port.size;
            }
            this.editor.changed();
          }),
        ]),
        el("td", {}, [
          textInput(port.unit ?? "", (value) => {
            port.unit = value.trim() || undefined;
            this.editor.changed();
          }),
        ]),
        el("td", {}, [
          textInput(port.description ?? "", (value) => {
            port.description = value.trim() || undefined;
            this.editor.changed();
          }),
        ]),
        el("td", { text: used.has(port.name) ? "" : "unused", title: used.has(port.name) ? "" : "No input file uses this input" }),
        el("td", {}, [
          button("×", () => {
            inputs.splice(index, 1);
            this.editor.changed();
          }, { title: "Remove the input (its markers stay)" }),
        ]),
      ]),
    );
    this.ports.replaceChildren(
      el("h3.section-title", { text: `Inputs (${inputs.length})` }),
      el("table.wrapper-table", {}, [
        el("tr", {}, ["Name", "Type", "Default", "Unit", "Description", "", ""].map((title) => el("th", { text: title }))),
        ...rows,
      ]),
      button("Add input", () => {
        spec.inputs = [...inputs, { name: `x_${inputs.length + 1}`, default: 0 }];
        this.editor.changed();
      }, { title: "An input without marker, e.g. used by the command" }),
    );
  }
}

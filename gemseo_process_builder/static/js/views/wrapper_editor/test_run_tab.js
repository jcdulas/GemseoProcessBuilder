// @ts-check
// The Test run tab of the wrapper editor: run the wrapper once in the worker.
//
// The working folder is kept, so that the user can look at the files the code
// read and wrote.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { button, formatValueInput, parseValueInput, textInput } from "./fields.js";

export class TestRunTab {
  /**
   * @param {HTMLElement} page
   * @param {import("./editor.js").WrapperEditor} editor
   */
  constructor(page, editor) {
    this.page = page;
    this.editor = editor;
    /** @type {Record<string, any>} - Input values typed by the user, by name. */
    this.values = {};
    /** @type {any} */
    this.report = null;
    this.running = false;
  }

  render() {
    const inputs = this.editor.spec.inputs ?? [];
    const rows = inputs.map((/** @type {any} */ port) =>
      el("tr", {}, [
        el("td", { text: port.name }),
        el("td", {}, [
          textInput(formatValueInput(this.values[port.name] ?? port.default ?? 0), (value) => {
            this.values[port.name] = parseValueInput(value);
          }),
        ]),
        el("td", { text: port.unit ?? "" }),
      ]),
    );
    const run = button(this.running ? "Running…" : "Run", () => this.run(), { primary: true, title: "Run the wrapper once, in the worker" });
    run.toggleAttribute("disabled", this.running);
    this.page.replaceChildren(
      el("div.wrapper-form", {}, [
        el("h3.section-title", { text: "Input values" }),
        inputs.length ? el("table.wrapper-table", {}, [el("tr", {}, ["Input", "Value", "Unit"].map((title) => el("th", { text: title }))), ...rows]) : el("div.form-hint", { text: "The wrapper has no inputs." }),
        el("div.wrapper-list-row", {}, [run, button("Default values", () => ((this.values = {}), this.render()))]),
        this.renderReport(),
      ]),
    );
  }

  /** The inputs of the run, as the discipline takes them. */
  inputData() {
    /** @type {Record<string, any>} */
    const data = {};
    for (const port of this.editor.spec.inputs ?? []) {
      const value = this.values[port.name] ?? port.default ?? 0;
      data[port.name] = port.dtype === "str" || port.dtype === "path" ? String(value) : Array.isArray(value) ? value : [value];
    }
    return data;
  }

  async run() {
    this.running = true;
    this.render();
    try {
      this.report = await app.api.call("executable.testRun", { spec: this.editor.spec, inputs: this.inputData(), base_folder: this.editor.baseFolder });
    } catch (error) {
      showError("The wrapper could not run", error);
    } finally {
      this.running = false;
      if (this.editor.view === "test") {
        this.render();
      }
    }
  }

  renderReport() {
    const report = this.report;
    if (!report) {
      return el("div");
    }
    const outputs = Object.entries(report.outputs ?? {});
    return el("div.wrapper-report", {}, [
      el("h3.section-title", { text: "Result" }),
      report.error ? el("pre.wrapper-error", { text: report.error }) : el("div.wrapper-success", { text: "The run succeeded." }),
      outputs.length
        ? el("table.wrapper-table", {}, [
            el("tr", {}, ["Output", "Value"].map((title) => el("th", { text: title }))),
            ...outputs.map(([name, value]) => el("tr", {}, [el("td", { text: name }), el("td", { text: formatValueInput(value) })])),
          ])
        : null,
      el("div.wrapper-facts", {}, [
        el("div", { text: `Command: ${report.command}` }),
        el("div", { text: `Return code: ${report.returncode ?? "—"}` }),
        report.workdir
          ? el("div.wrapper-list-row", {}, [
              el("span", { text: `Working folder: ${report.workdir}` }),
              button("Open folder", () => app.api.call("executable.reveal", { path: report.workdir }).catch((error) => showError("The folder could not be opened", error))),
            ])
          : null,
      ]),
      el("h3.section-title", { text: "Standard output" }),
      el("pre.wrapper-output", { text: report.stdout || "(empty)" }),
      el("h3.section-title", { text: "Standard error" }),
      el("pre.wrapper-output", { text: report.stderr || "(empty)" }),
      el("div.wrapper-list-row", {}, [
        report.stdout
          ? button("Use as sample output", () => {
              this.editor.outputSamples.stdout = report.stdout;
              this.editor.show("outputs");
            }, { title: "Select values of the standard output in the Outputs tab" })
          : null,
        ...this.outputFiles().map((file) => button(`Use ${file} as sample`, () => this.useFile(report.workdir, file))),
      ]),
    ]);
  }

  /** The files the rules read, to take as samples from the working folder. */
  outputFiles() {
    const spec = this.editor.spec;
    const files = new Set((spec.rules ?? []).filter((/** @type {any} */ rule) => rule.kind !== "file").map((/** @type {any} */ rule) => rule.file ?? "stdout"));
    if (spec.output_file) {
      files.add(spec.output_file);
    }
    files.delete("stdout");
    return this.report?.workdir ? [...files] : [];
  }

  /**
   * @param {string} folder
   * @param {string} file
   */
  async useFile(folder, file) {
    try {
      const { text } = await app.api.call("executable.readSample", { path: `${folder}/${file}` });
      this.editor.outputSamples[file] = text;
      this.editor.show("outputs");
    } catch (error) {
      showError(`${file} could not be read`, error);
    }
  }
}

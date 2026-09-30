// @ts-check
// The Command tab of the wrapper editor: what to run, where and how long.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { button, parseNumberInput, row, selectInput, textInput } from "./fields.js";

const TOKENS = [
  ["{python}", "The Python of the process running the wrapper"],
  ["{input_file}", "The input file (the first template by default)"],
  ["{output_file}", "The output file"],
  ["{workdir}", "The working folder of the run"],
];

const RETENTIONS = /** @type {[string, string][]} */ ([
  ["on_error", "Keep the folders of failed runs"],
  ["always", "Keep all the folders"],
  ["never", "Remove all the folders"],
]);

/** A path for a command line, quoted when it has spaces. */
function quoted(path) {
  return /\s/.test(path) ? `"${path}"` : path;
}

export class CommandTab {
  /**
   * @param {HTMLElement} page
   * @param {import("./editor.js").WrapperEditor} editor
   */
  constructor(page, editor) {
    this.page = page;
    this.editor = editor;
  }

  /**
   * Change a field of the spec; empty values fall back to the defaults.
   *
   * @param {string} key
   * @param {any} value
   */
  set(key, value) {
    const spec = this.editor.spec;
    if (value === "" || value === null || (Array.isArray(value) && !value.length)) {
      delete spec[key];
    } else {
      spec[key] = value;
    }
    this.editor.changed();
  }

  render() {
    const spec = this.editor.spec;
    const command = /** @type {HTMLTextAreaElement} */ (el("textarea.input.form-textarea.wrapper-command", { rows: 2, spellcheck: "false", placeholder: "solver.exe {input_file}" }));
    command.value = spec.command ?? "";
    command.addEventListener("change", () => this.set("command", command.value.trim()));
    /** @param {string} text */
    const insert = (text) => {
      const start = command.selectionStart ?? command.value.length;
      command.value = command.value.slice(0, start) + text + command.value.slice(command.selectionEnd ?? start);
      this.set("command", command.value.trim());
    };
    const tokens = el(
      "div.wrapper-tokens",
      {},
      TOKENS.map(([token, title]) => el("button.button.bordered.small", { text: token, title, onClick: () => insert(token) })),
    );
    const browseExecutable = button("Executable…", async () => {
      const path = await app.api.call("dialog.openFile", { title: "Executable", filter: "All files (*)" });
      if (path) {
        insert(`${quoted(path)} `);
      }
    });

    this.page.replaceChildren(
      el("div.wrapper-form", {}, [
        el("h3.section-title", { text: "Command" }),
        row("Name", textInput(spec.name, (value) => this.set("name", value.trim())), "The name of the discipline."),
        row("Command line", el("div", {}, [command, el("div.wrapper-tokens", {}, [browseExecutable, tokens])]), "Run in the working folder of each run, in a shell."),
        row("Input file", textInput(spec.input_file ?? "", (value) => this.set("input_file", value.trim()), { placeholder: spec.templates?.[0]?.target ?? "" }), "The file of {input_file}; the first input file by default."),
        row("Output file", textInput(spec.output_file ?? "", (value) => this.set("output_file", value.trim()), { placeholder: "output.txt" }), "The file of {output_file}."),
        row("Timeout (s)", textInput(spec.timeout == null ? "" : String(spec.timeout), (value) => this.set("timeout", parseNumberInput(value, null)), { placeholder: "None" }), "Empty: wait whatever the duration."),
        row(
          "Success codes",
          textInput((spec.return_codes ?? [0]).join(", "), (value) => {
            const codes = value.split(/[\s,]+/).filter(Boolean).map(Number).filter(Number.isInteger);
            this.set("return_codes", codes.length === 1 && codes[0] === 0 ? [] : codes);
          }),
          "The return codes of a successful run.",
        ),
        row("Error patterns", this.patterns(), "Regular expressions failing a run when found in its output, one per line."),
        el("h3.section-title", { text: "Environment" }),
        this.environment(),
        el("h3.section-title", { text: "Working folders" }),
        row("Create in", this.folderInput(), "The temporary folder by default."),
        row("Keep", selectInput(spec.retention ?? "on_error", RETENTIONS, (value) => this.set("retention", value === "on_error" ? "" : value))),
        el("h3.section-title", { text: "Files to copy" }),
        this.files(),
      ]),
    );
  }

  patterns() {
    const area = /** @type {HTMLTextAreaElement} */ (el("textarea.input.form-textarea", { rows: 2, spellcheck: "false", placeholder: "Traceback|ERROR" }));
    area.value = (this.editor.spec.error_patterns ?? []).join("\n");
    area.addEventListener("change", () =>
      this.set(
        "error_patterns",
        area.value
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean),
      ),
    );
    return area;
  }

  folderInput() {
    const spec = this.editor.spec;
    const input = textInput(spec.workdir_root ?? "", (value) => this.set("workdir_root", value.trim()), { placeholder: "Temporary folder" });
    const browse = button("Browse…", async () => {
      const path = await app.api.call("dialog.openFolder", { title: "Folder of the working folders" });
      if (path) {
        this.set("workdir_root", path);
      }
    });
    return el("div.input-with-button", {}, [input, browse]);
  }

  /** Environment variables, as name = value rows. */
  environment() {
    const variables = Object.entries(this.editor.spec.environment ?? {});
    /** @param {[string, string][]} entries */
    const commit = (entries) => this.set("environment", Object.fromEntries(entries.filter(([name]) => name.trim())));
    const rows = variables.map(([name, value], index) =>
      el("div.wrapper-list-row", {}, [
        textInput(name, (text) => commit(variables.map((entry, i) => (i === index ? [text.trim(), entry[1]] : entry))), { className: "input" }),
        el("span", { text: "=" }),
        textInput(value, (text) => commit(variables.map((entry, i) => (i === index ? [entry[0], text] : entry))), { className: "input" }),
        button("Remove", () => commit(variables.filter((_, i) => i !== index))),
      ]),
    );
    const add = button("Add variable", () => {
      this.editor.spec.environment = { ...(this.editor.spec.environment ?? {}), [`NAME_${variables.length + 1}`]: "" };
      this.editor.changed();
    });
    return el("div.wrapper-list", {}, [...rows, add]);
  }

  /** Files and folders copied in each working folder. */
  files() {
    const spec = this.editor.spec;
    const files = spec.files ?? [];
    /** @param {string | null} path */
    const add = (path) => {
      if (path && !files.includes(path)) {
        this.set("files", [...files, path]);
      }
    };
    return el("div.wrapper-list", {}, [
      ...files.map((/** @type {string} */ path, /** @type {number} */ index) =>
        el("div.wrapper-list-row", {}, [
          el("span.wrapper-path", { text: path }),
          button("Remove", () => this.set("files", files.filter((/** @type {string} */ _, /** @type {number} */ i) => i !== index))),
        ]),
      ),
      el("div.wrapper-list-row", {}, [
        button("Add file…", async () => add(await app.api.call("dialog.openFile", { title: "File to copy" }))),
        button("Add folder…", async () => add(await app.api.call("dialog.openFolder", { title: "Folder to copy" }))),
      ]),
    ]);
  }
}

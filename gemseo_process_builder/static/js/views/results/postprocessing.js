// @ts-check
// GEMSEO's own post-processings of a finished run: pick one, set its
// settings, run it in the worker, and browse the figures it saved.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { openImageViewer } from "../../components/image_viewer.js";
import { askConfirmation } from "../../components/modal.js";
import { settingsForm } from "../../forms/schema_form.js";
import { explain } from "./common.js";

/** The layout key remembering the last settings of each post-processing. */
const SETTINGS_KEY = "postproc_settings";

/** A post-processing may take long (SOM, QuadApprox on large histories). */
const RUN_TIMEOUT_MS = 3_600_000;

/**
 * The URL of a file of a run, served by the ``gpb://run/`` route.
 *
 * @param {string} runId
 * @param {string} path - Relative to the run folder.
 */
export function runFileUrl(runId, path) {
  return `gpb://run/${encodeURIComponent(runId)}/${path.split("/").map(encodeURIComponent).join("/")}`;
}

/** @returns {Record<string, Record<string, any>>} */
function rememberedSettings() {
  return app.store.state.view[`extra.${SETTINGS_KEY}`] ?? {};
}

export class PostprocessingView {
  /** @param {HTMLElement} root */
  constructor(root) {
    root.classList.add("postproc-view");
    this.root = root;
    this.side = el("div.postproc-side");
    this.gallery = el("div.postproc-gallery");
    /** @type {import("./source.js").ResultsSource | null} */
    this.source = null;
    /** @type {{name: string, description: string, schema: any}[]} */
    this.available = [];
    /** @type {any[]} */
    this.results = [];
    this.selected = "";
    /** @type {Record<string, any>} */
    this.settings = {};
    this.running = false;
    this.loadedFor = "";
  }

  /** @param {import("./source.js").ResultsSource} source */
  async update(source) {
    this.source = source;
    if (source.live || !source.info) {
      explain(this.root, "The post-processings are available when the run ends.");
      this.loadedFor = "";
      return;
    }
    if (this.loadedFor === source.runId) {
      return;
    }
    this.loadedFor = source.runId;
    this.root.replaceChildren(this.side, this.gallery);
    this.side.replaceChildren(el("p.placeholder", { text: "Loading the post-processings…" }));
    this.gallery.replaceChildren();
    try {
      [this.available, this.results] = await Promise.all([
        app.api.call("postproc.list", { id: source.runId }, { timeout: 60_000 }),
        app.api.call("postproc.results", { id: source.runId }, { timeout: 60_000 }),
      ]);
    } catch (error) {
      this.loadedFor = "";
      this.side.replaceChildren(el("p.placeholder", { text: `The post-processings are not available: ${/** @type {any} */ (error).message}` }));
      return;
    }
    if (!this.available.some((item) => item.name === this.selected)) {
      this.select(this.available[0]?.name ?? "");
    } else {
      this.renderSide();
    }
    this.renderGallery();
  }

  /** @param {string} name */
  select(name) {
    this.selected = name;
    this.settings = { ...(rememberedSettings()[name] ?? {}) };
    this.renderSide();
  }

  renderSide() {
    const current = this.available.find((item) => item.name === this.selected);
    const list = el(
      "div.postproc-list",
      { role: "listbox" },
      this.available.map((item) =>
        el(`button.postproc-item${item.name === this.selected ? ".active" : ""}`, { title: item.description, onClick: () => this.select(item.name) }, [
          el("span.postproc-name", { text: item.name }),
          el("span.postproc-description", { text: item.description }),
        ]),
      ),
    );
    if (!current) {
      this.side.replaceChildren(list);
      return;
    }
    const form = settingsForm({
      schema: current.schema,
      kind: "postprocessing",
      name: current.name,
      settings: this.settings,
      onChange: (settings) => {
        this.settings = settings;
        this.renderSide();
      },
    });
    const actions = this.running
      ? [
          el("span.postproc-spinner", { "aria-label": "Running" }),
          el("span", { text: `Running ${current.name}…` }),
          el("button.button.bordered", { text: "Cancel", onClick: () => this.cancel() }),
        ]
      : [
          el("button.button.primary", { text: `Run ${current.name}`, onClick: () => this.run() }),
          Object.keys(this.settings).length
            ? el("button.button.bordered", {
                text: "Reset settings",
                onClick: () => {
                  this.settings = {};
                  this.renderSide();
                },
              })
            : null,
        ];
    this.side.replaceChildren(
      list,
      el("div.postproc-settings", {}, [
        el("h3.section-title", { text: `${current.name} settings` }),
        el("p.form-hint", { text: current.description }),
        form.element,
        el("div.postproc-actions", {}, actions),
      ]),
    );
  }

  async run() {
    const source = this.source;
    if (!source || this.running) {
      return;
    }
    const name = this.selected;
    const settings = this.settings;
    this.running = true;
    this.renderSide();
    try {
      const result = await app.api.call("postproc.run", { id: source.runId, name, settings }, { timeout: RUN_TIMEOUT_MS });
      this.results = [result, ...this.results];
      this.renderGallery();
      await this.remember(name, settings);
    } catch (error) {
      if (/** @type {any} */ (error).code !== "cancelled") {
        showError(`${name} failed`, error);
      }
    } finally {
      this.running = false;
      this.renderSide();
    }
  }

  async cancel() {
    try {
      await app.api.call("postproc.cancel");
    } catch (error) {
      showError("The post-processing could not be cancelled", error);
    }
  }

  /**
   * Keep the settings in the project, for the next time.
   *
   * @param {string} name
   * @param {Record<string, any>} settings
   */
  async remember(name, settings) {
    const all = { ...rememberedSettings(), [name]: settings };
    if (!Object.keys(settings).length) {
      delete all[name];
    }
    try {
      await app.store.execute({ type: "setLayout", extra: { [SETTINGS_KEY]: all } }, { undoable: false });
    } catch (error) {
      console.error(error);
    }
  }

  renderGallery() {
    const source = this.source;
    if (!source) {
      return;
    }
    if (!this.results.length) {
      this.gallery.replaceChildren(el("p.placeholder", { text: "Run a post-processing: its figures appear here." }));
      return;
    }
    this.gallery.replaceChildren(
      ...this.results.map((result) => {
        const images = result.files.map((/** @type {string} */ file) => ({
          src: runFileUrl(source.runId, file),
          title: `${result.name}: ${file.split("/").pop()}`,
        }));
        const settings = Object.entries(result.settings ?? {})
          .map(([key, value]) => `${key} = ${JSON.stringify(value)}`)
          .join(", ");
        return el("section.postproc-result", {}, [
          el("div.postproc-result-header", {}, [
            el("span.postproc-name", { text: result.name }),
            el("span.form-hint", { text: result.created.replace("T", " ") }),
            el("span.toolbar-spacer"),
            el("button.button.bordered", { text: "Open folder", onClick: () => this.call("postproc.reveal", result) }),
            el("button.button.bordered", { text: "Delete", onClick: () => this.delete(result) }),
          ]),
          settings ? el("div.form-hint", { text: settings }) : null,
          el(
            "div.postproc-thumbnails",
            {},
            images.length
              ? images.map((/** @type {{src: string, title: string}} */ image, /** @type {number} */ index) =>
                  el("button.postproc-thumbnail", { title: image.title, onClick: () => openImageViewer(images, index) }, [
                    el("img", { src: image.src, alt: image.title, loading: "lazy" }),
                  ]),
                )
              : [el("p.placeholder", { text: "No figure was saved." })],
          ),
        ]);
      }),
    );
  }

  /** @param {any} result */
  async delete(result) {
    if (!(await askConfirmation("Delete the figures", `Delete the figures of ${result.name} (${result.created.replace("T", " ")})?`, "Delete"))) {
      return;
    }
    if (await this.call("postproc.delete", result)) {
      this.results = this.results.filter((item) => item.id !== result.id);
      this.renderGallery();
    }
  }

  /**
   * @param {string} method
   * @param {any} result
   * @returns {Promise<boolean>} Whether the call succeeded.
   */
  async call(method, result) {
    try {
      await app.api.call(method, { id: this.source?.runId, result: result.id });
      return true;
    } catch (error) {
      showError("The action failed", error);
      return false;
    }
  }
}

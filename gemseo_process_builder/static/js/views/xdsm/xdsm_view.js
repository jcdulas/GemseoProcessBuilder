// @ts-check
// The XDSM tab (SPEC § 8.5): the process of a driver, as GEMSEO describes it.
//
// The worker builds the scenario of the generated script and returns GEMSEO's
// XDSM JSON; ``renderer.js`` draws it. The tab follows the selection: the
// selected driver, else the driver around the selection or the level shown,
// else the first study of the model. It refreshes after changes of the model,
// only while it is visible.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { scenarioName } from "../../lib/xdsm_layout.js";
import { pictureOf, registerImageSource } from "../../services/export.js";
import { mountXdsm } from "./renderer.js";

const TAB_ID = "xdsm";

/**
 * The picture of an XDSM drawn by ``mountXdsm``, at its natural size whatever
 * the zoom.
 *
 * @param {SVGSVGElement} svg
 * @param {string} title
 */
export function xdsmPicture(svg, title) {
  const zoomed = /** @type {SVGGElement[]} */ ([...svg.querySelectorAll(":scope > g[transform]")]);
  const transforms = zoomed.map((group) => group.getAttribute("transform") ?? "");
  zoomed.forEach((group) => group.removeAttribute("transform"));
  try {
    return pictureOf(svg, { title });
  } finally {
    zoomed.forEach((group, index) => group.setAttribute("transform", transforms[index]));
  }
}
const REFRESH_DELAY_MS = 800;
const SCENARIO_KINDS = ["optimization", "doe", "parametric"];

/** @param {any} node */
function isStudy(node) {
  return node?.type === "driver" && SCENARIO_KINDS.includes(node.kind);
}

/** The first study of the model, looking through assemblies. */
function firstStudy() {
  /** @param {string} id */
  const search = (id) => {
    for (const child of app.store.children(id)) {
      if (isStudy(child)) {
        return child.id;
      }
      if (child.type === "assembly") {
        const found = search(child.id);
        if (found) {
          return found;
        }
      }
    }
    return null;
  };
  return search(app.store.rootId);
}

/**
 * The driver whose XDSM to show: a study at or around a node, else the first one.
 *
 * @param {string | null} id
 * @returns {string | null}
 */
export function xdsmTarget(id) {
  if (id) {
    for (const nodeId of [...app.store.pathTo(id)].reverse()) {
      if (isStudy(app.store.node(nodeId))) {
        return nodeId;
      }
    }
  }
  return firstStudy();
}

class XdsmView {
  /** @param {HTMLElement} page */
  constructor(page) {
    this.page = page;
    page.classList.add("xdsm-view");
    this.follow = true;
    /** @type {string | null} */
    this.target = null;
    this.stale = true;
    this.token = 0;
    this.timer = 0;
    /** Set while the XDSM itself selects a node, so that it does not follow. */
    this.selecting = false;
    /** @type {any} - Node ids by name, from the last build. */
    this.nodes = null;
    /** @type {ReturnType<typeof mountXdsm> | null} */
    this.renderer = null;
    const followBox = /** @type {HTMLInputElement} */ (el("input", { type: "checkbox", checked: true }));
    followBox.addEventListener("change", () => {
      this.follow = followBox.checked;
      this.followSelection();
    });
    this.title = el("span.n2-title");
    this.pdfButton = /** @type {HTMLButtonElement} */ (
      el("button.button.bordered", { text: "Export PDF…", disabled: true, onClick: () => this.export("pdf") })
    );
    this.host = el("div.xdsm-host");
    page.replaceChildren(
      el("div.results-toolbar", {}, [
        this.title,
        el("label.form-check", { title: "Show the XDSM of the selected driver" }, [followBox, el("span", { text: "Follow selection" })]),
        el("span.toolbar-spacer"),
        el("span.form-hint", { text: "Double-click a sub-optimization to open its XDSM." }),
        el("button.button.bordered", { text: "Refresh", onClick: () => this.load() }),
        el("button.button.bordered", { text: "Fit", onClick: () => this.renderer?.fit() }),
        el("button.button.bordered", { text: "Export HTML…", onClick: () => this.export("html") }),
        this.pdfButton,
        el("button.button.bordered", { text: "Export image…", onClick: () => app.actions.invoke("file.exportImage") }),
      ]),
      this.host,
    );
    app.selection.onChange(() => this.followSelection());
    app.navigation.onChange(() => this.followSelection());
    app.api.on("resolution.updated", () => this.changed());
    app.store.subscribe((event) => {
      if (event.type === "reset") {
        this.target = null;
      }
      this.changed();
    });
    // The host gets a size when the tab is shown: refresh it if needed.
    new ResizeObserver(() => {
      if (this.visible() && this.stale) {
        this.load();
      }
    }).observe(this.host);
    this.checkPdf();
    this.followSelection(true);
  }

  visible() {
    return app.tabs.center.active === TAB_ID && this.host.clientWidth > 0;
  }

  /** @param {boolean} [force] */
  followSelection(force = false) {
    if (!this.follow || this.selecting) {
      return;
    }
    const ids = app.selection.list();
    const target = xdsmTarget(ids.length === 1 ? ids[0] : app.navigation.current());
    if (force || target !== this.target) {
      this.target = target;
      this.stale = true;
      if (this.visible() || force) {
        this.load();
      }
    }
  }

  /** The model changed: refresh a little later, when the tab is shown. */
  changed() {
    this.stale = true;
    clearTimeout(this.timer);
    this.timer = window.setTimeout(() => {
      if (this.visible()) {
        this.load();
      }
    }, REFRESH_DELAY_MS);
  }

  /** @param {string} text */
  message(text) {
    this.renderer = null;
    this.host.replaceChildren(el("p.placeholder", { text }));
  }

  async load() {
    this.stale = false;
    const target = this.target ?? xdsmTarget(null);
    this.target = target;
    if (!target) {
      this.title.textContent = "XDSM";
      this.message("Add an optimization, a DOE or a parametric study: the XDSM shows its process.");
      return;
    }
    this.title.textContent = `XDSM of ${app.store.node(target)?.name ?? target}`;
    const token = ++this.token;
    if (!this.renderer) {
      this.host.replaceChildren(el("p.placeholder", { text: "Building the XDSM…" }));
    }
    let result;
    try {
      result = await app.api.call("xdsm.build", { target }, { timeout: 90_000 });
    } catch (error) {
      if (token === this.token) {
        this.message(`The XDSM cannot be built: ${/** @type {any} */ (error).message}`);
      }
      return;
    }
    if (token !== this.token) {
      return;
    }
    this.nodes = result.nodes;
    if (this.renderer) {
      this.renderer.update(result.diagrams);
    } else {
      this.host.replaceChildren();
      this.renderer = mountXdsm(this.host, result.diagrams, { onNodeClick: (event) => this.select(event) });
    }
  }

  /**
   * Select the node of the model behind a box of the XDSM.
   *
   * @param {{diagram: string, node: {id: string, name: string, type: string}}} event
   */
  select({ diagram, node }) {
    const nodes = this.nodes;
    if (!nodes) {
      return;
    }
    let id;
    if (node.id === "Opt") {
      id = diagram === "root" ? nodes.target : nodes.scenarios[scenarioName(diagram)];
    } else if (node.type === "mdo") {
      id = nodes.scenarios[scenarioName(node.name)];
    } else {
      id = nodes.disciplines[node.name];
    }
    if (!id) {
      return; // An MDA created by the formulation: no node of the model.
    }
    this.selecting = true;
    try {
      app.selection.set([id]);
    } finally {
      this.selecting = false;
    }
  }

  async checkPdf() {
    try {
      const capabilities = await app.api.call("xdsm.capabilities", {}, { timeout: 60_000 });
      this.pdfButton.disabled = !capabilities.pdf;
      this.pdfButton.title = capabilities.pdf ? "Export the XDSM as a PDF file (pyXDSM and LaTeX)" : capabilities.reason;
    } catch (error) {
      this.pdfButton.title = "The worker is not available.";
    }
  }

  /** @param {"html" | "pdf"} format */
  async export(format) {
    const target = this.target;
    if (!target) {
      return;
    }
    const name = app.store.node(target)?.name ?? "xdsm";
    try {
      const state = await app.api.call("project.state");
      const folder = state.path ? state.path.replace(/[\\/][^\\/]*$/, "") : "";
      const path = await app.api.call(
        "dialog.saveFile",
        {
          title: `Export the XDSM of ${name}`,
          filter: format === "html" ? "HTML files (*.html)" : "PDF files (*.pdf)",
          start: `${folder ? `${folder}/` : ""}${name}_xdsm.${format}`,
        },
        { timeout: 24 * 3600 * 1000 }, // The dialog waits for the user.
      );
      if (!path) {
        return;
      }
      const method = format === "html" ? "xdsm.exportHtml" : "xdsm.exportPdf";
      const written = await app.api.call(method, { target, path }, { timeout: 180_000 });
      console.info(`Exported the XDSM of ${name} to ${written}`);
    } catch (error) {
      showError("The XDSM could not be exported", error);
    }
  }
}

/** @type {XdsmView | null} */
let opened = null;

/**
 * Open the XDSM tab, showing a driver (or the one around the selection).
 *
 * @param {string} [driverId]
 */
export function openXdsm(driverId) {
  const page = app.tabs.center.open({ id: TAB_ID, title: "XDSM", onClose: () => (opened = null) });
  if (!opened) {
    opened = new XdsmView(page);
  }
  if (driverId) {
    opened.target = xdsmTarget(driverId);
    opened.load();
  } else if (opened.stale) {
    opened.load();
  }
}

export function installXdsm() {
  app.actions.handle("view.xdsm", { run: () => openXdsm() });
  registerImageSource(TAB_ID, {
    name: "xdsm",
    produce: async () => {
      const svg = /** @type {SVGSVGElement | null} */ (opened?.host.querySelector("svg.xdsm-svg") ?? null);
      if (!svg) {
        throw new Error("The XDSM is not shown.");
      }
      return xdsmPicture(svg, opened?.title.textContent ?? "XDSM");
    },
  });
}

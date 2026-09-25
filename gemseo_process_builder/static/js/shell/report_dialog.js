// @ts-check
// File › Export › Report… (SPEC § 13): choose the content of the report, draw
// its diagrams (the whole model, its N2 and the XDSM of each study), then let
// Python build the standalone HTML file or print it to PDF.
import { app } from "../app.js";
import { el } from "../components/dom.js";
import { showError } from "../components/errors.js";
import { openModal } from "../components/modal.js";
import { collapse } from "../lib/n2_layout.js";
import { fileStem } from "../services/export.js";
import { n2Picture } from "../views/n2/n2_view.js";
import { mountXdsm } from "../views/xdsm/renderer.js";
import { xdsmPicture } from "../views/xdsm/xdsm_view.js";

const STUDY_KINDS = ["optimization", "doe", "parametric"];

const SECTIONS = [
  ["description", "Project description"],
  ["diagrams", "Diagrams (workflow, N2, XDSM of each study)"],
  ["inventory", "Components and variables"],
  ["problem", "Problem definition (design space, objectives, constraints, algorithms)"],
];

/**
 * A checkbox with its label.
 *
 * @param {string} label
 * @param {boolean} checked
 */
function checkbox(label, checked) {
  const box = /** @type {HTMLInputElement} */ (el("input", { type: "checkbox" }));
  box.checked = checked;
  return { box, row: el("label.wizard-check", {}, [box, el("span", { text: label })]) };
}

/** The studies of the model: the drivers whose XDSM the report shows. */
function studies() {
  return Object.values(app.store.state.nodes).filter((node) => node.type === "driver" && STUDY_KINDS.includes(node.kind));
}

/**
 * The diagrams of the report, drawn out of sight.
 *
 * @param {(text: string) => void} progress
 * @returns {Promise<{title: string, svg: string}[]>}
 */
export async function drawDiagrams(progress) {
  const root = app.store.rootId;
  const name = app.store.node(root)?.name ?? "Model";
  const diagrams = [];
  progress("Drawing the workflow…");
  const workflow = await app.canvas.picture({ full: true });
  diagrams.push({ title: `Workflow of ${name}, containers expanded`, svg: workflow.svg });
  // A hidden box gives the diagrams the styles of the page.
  const host = el("div.report-drawing");
  document.body.append(host);
  try {
    // The N2 of the model, and of each driver: the content of a driver is its own level.
    const drivers = Object.values(app.store.state.nodes).filter((node) => node.type === "driver");
    for (const level of [app.store.node(root), ...drivers]) {
      progress(`Drawing the N2 of ${level.name}…`);
      const view = collapse(await app.api.call("n2.build", { level: level.id }), new Set());
      if (view.entries.length >= 2) {
        diagrams.push({ title: `N2 of ${level.name}`, svg: n2Picture(host, view, `N2 of ${level.name}`).svg });
      }
    }
    for (const study of studies()) {
      progress(`Building the XDSM of ${study.name}…`);
      try {
        const result = await app.api.call("xdsm.build", { target: study.id }, { timeout: 90_000 });
        mountXdsm(host, result.diagrams);
        const svg = /** @type {SVGSVGElement} */ (host.querySelector("svg.xdsm-svg"));
        diagrams.push({ title: `XDSM of ${study.name}`, svg: xdsmPicture(svg, `XDSM of ${study.name}`).svg });
      } catch (error) {
        console.warn(`The XDSM of ${study.name} is left out of the report:`, error);
      }
    }
  } finally {
    host.remove();
  }
  return diagrams;
}

export async function openReportDialog() {
  let sources;
  try {
    sources = await app.api.call("report.sources");
  } catch (error) {
    showError("The runs could not be read", error);
    return;
  }
  // Empty: the name of the project.
  const title = /** @type {HTMLInputElement} */ (el("input.input", { type: "text", placeholder: "The project name" }));
  const format = /** @type {HTMLSelectElement} */ (
    el("select.select", {}, [el("option", { value: "html", text: "HTML (one file, opens offline)" }), el("option", { value: "pdf", text: "PDF (A4)" })])
  );
  const sections = SECTIONS.map(([key, label]) => ({ key, ...checkbox(label, true) }));
  const runs = sources.map((/** @type {any} */ run) => {
    const choice = checkbox(`${run.name} — ${run.driver} (${run.status})`, false);
    const postprocessings = run.postprocessings.map((/** @type {string} */ result) => ({
      result,
      ...checkbox(result.replace(/-\d[\d-]*$/, ""), false),
    }));
    return { run, ...choice, postprocessings };
  });
  const progress = el("div.form-hint");
  const body = el("div.report-form", {}, [
    el("label.form-row", {}, [el("span.form-label", { text: "Title" }), title]),
    el("label.form-row", {}, [el("span.form-label", { text: "Format" }), format]),
    el("h4", { text: "Content" }),
    ...sections.map((item) => item.row),
    el("h4", { text: "Results" }),
    runs.length
      ? el(
          "div.report-runs",
          {},
          runs.map((item) =>
            el("div", {}, [item.row, item.postprocessings.length ? el("div.report-postprocessings", {}, item.postprocessings.map((/** @type {any} */ post) => post.row)) : null]),
          ),
        )
      : el("p.form-hint", { text: "The project has no run." }),
    progress,
  ]);
  openModal({
    title: "Export report",
    body,
    buttons: [
      { label: "Cancel" },
      {
        label: "Export…",
        primary: true,
        onClick: async () => {
          /** @type {Record<string, any>} */
          const options = { title: title.value.trim() };
          for (const item of sections) {
            options[item.key] = item.box.checked;
          }
          options.runs = runs.filter((item) => item.box.checked).map((item) => item.run.id);
          options.postprocessings = runs.flatMap((item) =>
            item.postprocessings.filter((/** @type {any} */ post) => post.box.checked).map((/** @type {any} */ post) => ({ run: item.run.id, result: post.result })),
          );
          const extension = format.value;
          const path = await app.api.call(
            "dialog.saveFile",
            { title: "Export report", filter: extension === "pdf" ? "PDF files (*.pdf)" : "HTML files (*.html)", start: `${fileStem(options.title || "report")}.${extension}` },
            { timeout: 24 * 3600 * 1000 },
          );
          if (!path) {
            return false;
          }
          try {
            const diagrams = options.diagrams ? await drawDiagrams((text) => (progress.textContent = text)) : [];
            progress.textContent = extension === "pdf" ? "Printing the PDF…" : "Writing the report…";
            const saved = await app.api.call("report.export", { path, format: extension, options, diagrams }, { timeout: 300_000 });
            console.info(`Report written to ${saved}`);
          } catch (error) {
            progress.textContent = "";
            showError("The report could not be exported", error);
            return false;
          }
        },
      },
    ],
  });
}

export function installReportExport() {
  app.actions.handle("file.exportReport", { run: () => openReportDialog() });
}

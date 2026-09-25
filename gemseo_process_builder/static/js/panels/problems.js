// @ts-check
// The Problems panel: validation errors, warnings and information.
import { app } from "../app.js";
import { el } from "../components/dom.js";
import { showError } from "../components/errors.js";
import { VirtualList } from "../components/virtual_list.js";

const LEVEL_ICONS = { error: "✖", warning: "⚠", info: "ℹ" };
const ROW_HEIGHT = 26;

export class ProblemsPanel {
  /** @param {HTMLElement} root */
  constructor(root) {
    root.replaceChildren();
    /** @type {Set<string>} */
    this.hidden = new Set();
    this.filters = el("div.problems-filters");
    this.list = el("div.problems-list");
    this.placeholder = el("p.placeholder");
    root.append(this.filters, this.placeholder, this.list);
    // Large models have thousands of problems: only the visible rows are drawn.
    /** @type {VirtualList<import("../services/validation.js").Problem>} */
    this.rows = new VirtualList(this.list, { renderRow: (problem) => this.row(problem), rowHeight: ROW_HEIGHT });
    app.validation.onChange(() => this.render());
    // Renamed nodes change the locations shown: the visible rows are drawn again.
    app.store.subscribe(() => this.rows.schedule());
    this.render();
  }

  /**
   * Show the node of a problem on the canvas.
   *
   * @param {import("../services/validation.js").Problem} problem
   */
  locate(problem) {
    if (!problem.node || !app.store.node(problem.node)) {
      return;
    }
    if (app.store.node(problem.node)?.parent) {
      app.navigation.reveal(problem.node);
      app.selection.set([problem.node]);
    } else {
      app.navigation.enter(problem.node);
    }
  }

  /**
   * @param {import("../services/validation.js").Problem} problem
   * @param {string} fix
   */
  async applyFix(problem, fix) {
    try {
      await app.api.call("validation.quickFix", { key: problem.key, fix });
    } catch (error) {
      showError("The problem could not be fixed", error);
    }
  }

  /**
   * The row of a problem.
   *
   * @param {import("../services/validation.js").Problem} problem
   */
  row(problem) {
    const path = problem.node ? app.store.pathTo(problem.node).map((id) => app.store.node(id)?.name).join(".") : "";
    return el(`div.problem.problem-${problem.level}`, { onClick: () => this.locate(problem) }, [
      el("span.problem-icon", { text: LEVEL_ICONS[problem.level] }),
      el("span.problem-message", { text: problem.message, title: problem.message }),
      el("span.problem-location", { text: path }),
      ...problem.quick_fixes.map((fix) =>
        el("button.button.bordered.problem-fix", {
          text: app.validation.fixLabels[fix] ?? fix,
          onClick: (/** @type {Event} */ event) => {
            event.stopPropagation();
            this.applyFix(problem, fix);
          },
        }),
      ),
    ]);
  }

  render() {
    const problems = app.validation.problems;
    const counts = { error: 0, warning: 0, info: 0 };
    for (const problem of problems) {
      counts[problem.level] += 1;
    }
    this.filters.replaceChildren(
      ...Object.entries(counts).map(([level, count]) =>
        el(`button.button.problems-filter${this.hidden.has(level) ? "" : ".active"}`, {
          text: `${LEVEL_ICONS[/** @type {keyof LEVEL_ICONS} */ (level)]} ${count} ${level}${count === 1 ? "" : "s"}`,
          onClick: () => {
            if (this.hidden.has(level)) {
              this.hidden.delete(level);
            } else {
              this.hidden.add(level);
            }
            this.render();
          },
        }),
      ),
    );
    const visible = problems.filter((problem) => !this.hidden.has(problem.level));
    this.placeholder.textContent = visible.length ? "" : problems.length ? "All problems are hidden by the filters." : "No problems found.";
    this.placeholder.hidden = Boolean(visible.length);
    this.rows.setRows(visible);
    app.tabs.bottom.setBadge("problems", counts.error + counts.warning);
  }
}

export function installValidation() {
  app.actions.handle("model.validate", {
    run: async () => {
      app.tabs.bottom.activate("problems");
      if (!app.layout.isVisible("bottom")) {
        app.layout.toggle("bottom");
      }
      await app.api.call("validation.run");
      // Then build the scripts in the worker, which reports what GEMSEO refuses.
      app.statusBar.set("validation", "Dry run…");
      try {
        await app.api.call("validation.dryRun", {}, { timeout: 180_000 });
      } catch (error) {
        showError("The dry run failed", error);
      } finally {
        app.statusBar.set("validation", "");
      }
    },
  });
}

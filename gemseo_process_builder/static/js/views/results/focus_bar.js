// @ts-check
// The filter of the Results views: which design variables and responses they
// show, for runs with many of them. The design variables can be ranked by
// sensitivity, by gradient or by the active set; the constraints limited to
// the active and violated ones (SPEC § 12.2).
import { el } from "../../components/dom.js";
import { MODES, describeFilter } from "../../lib/results_filter.js";
import { MAX_CHOICES, choice, labelled } from "./common.js";

const CONSTRAINTS = [
  { value: "all", label: "All" },
  { value: "active", label: "Active and violated" },
];

export class FocusBar {
  /**
   * @param {HTMLElement} root
   * @param {() => void} onChange - Called after the filter of the source changed.
   */
  constructor(root, onChange) {
    this.root = root;
    this.onChange = onChange;
    this.token = 0;
  }

  /** @param {import("./source.js").ResultsSource} source */
  async update(source) {
    const filter = source.filter;
    /** @param {Partial<import("../../lib/results_filter.js").FilterState>} change */
    const set = (change) => {
      source.filter = { ...filter, ...change };
      this.update(source);
      this.onChange();
    };
    const ranked = filter.mode === "sensitivity" || filter.mode === "gradient";
    // The objective first: the ranking is for it by default.
    const responses = source.columns
      .filter((column) => column.role !== "design variable" && column.name !== "feasible")
      .sort((a, b) => Number(b.role === "objective") - Number(a.role === "objective"))
      .slice(0, MAX_CHOICES)
      .map((column) => column.name);
    const count = /** @type {HTMLInputElement} */ (el("input.input.focus-count", { type: "number", min: "1", max: "500", value: String(filter.count) }));
    count.addEventListener("change", () => {
      const value = Math.max(1, Math.min(500, Math.round(Number(count.value)) || 10));
      set({ count: value });
    });
    const description = el("span.focus-description", { text: "…" });
    const controls = [
      labelled(
        "Design variables",
        choice(
          [],
          filter.mode,
          (value) => set({ mode: /** @type {any} */ (value) }),
          MODES,
        ),
      ),
      ranked ? labelled("for", choice(responses, filter.response || responses[0] || "", (value) => set({ response: value }))) : null,
      filter.mode !== "all" ? labelled("Top", count) : null,
      labelled(
        "Constraints",
        choice([], filter.constraints, (value) => set({ constraints: /** @type {any} */ (value) }), CONSTRAINTS),
      ),
      description,
    ];
    this.root.replaceChildren(...controls.filter((control) => control !== null));
    if (source.live) {
      description.textContent = "The filter applies when the run ends.";
      return;
    }
    const token = ++this.token;
    const focus = await source.focus();
    if (token !== this.token) {
      return;
    }
    description.textContent = focus.error || describeFilter(filter, focus, focus.ranking);
    description.classList.toggle("focus-error", Boolean(focus.error));
  }
}

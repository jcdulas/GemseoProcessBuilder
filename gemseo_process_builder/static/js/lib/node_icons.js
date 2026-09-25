// @ts-check
// The icon, label and color family of each kind of node.

/**
 * Stroke paths of the node icons, drawn in a 24×24 box. A segment of zero
 * length ("h.01") is painted as a dot by the round line caps.
 */
export const NODE_ICON_PATHS = {
  analytic: "M10 4.5H9a2 2 0 0 0-2 2V18a2 2 0 0 1-2 2H4 M4 11h7 M13.5 11.5l6 7 M19.5 11.5l-6 7",
  python_function:
    "M8 4H7a2 2 0 0 0-2 2v4l-2 2 2 2v4a2 2 0 0 0 2 2h1 M16 4h1a2 2 0 0 1 2 2v4l2 2-2 2v4a2 2 0 0 1-2 2h-1",
  python_class: "M12 3l8 4.5v9L12 21l-8-4.5v-9z M4 7.5l8 4.5 8-4.5 M12 12v9",
  executable: "M3.5 5h17v14h-17z M7 10l3 2.5L7 15 M12.5 15h4.5",
  surrogate:
    "M11 3l1.9 5.1L18 10l-5.1 1.9L11 17l-1.9-5.1L4 10l5.1-1.9z M18.5 15l.9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9z",
  assembly: "M4 4h7v7H4z M13 4h7v7h-7z M4 13h7v7H4z M13 13h7v7h-7z",
  mda: "M19.5 13a7.5 7.5 0 0 1-13.6 3.5 M4.5 11a7.5 7.5 0 0 1 13.6-3.5 M18.5 3.5v4h-4 M5.5 20.5v-4h4",
  doe: "M6 6h.01 M12 6h.01 M18 6h.01 M6 12h.01 M12 12h.01 M18 12h.01 M6 18h.01 M12 18h.01 M18 18h.01",
  optimization:
    "M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18z M12 7.5a4.5 4.5 0 1 0 0 9a4.5 4.5 0 1 0 0-9z M12 12h.01",
  parametric: "M4 7h9 M17 7h3 M15 4.5v5 M4 17h3 M11 17h9 M9 14.5v5",
};

/** Short labels of the node kinds. */
export const KIND_LABELS = {
  analytic: "Analytic",
  python_function: "Function",
  python_class: "Class",
  executable: "Executable",
  surrogate: "Surrogate",
  assembly: "Assembly",
  mda: "MDA",
  doe: "DOE",
  optimization: "Optimization",
  parametric: "Parametric",
};

/** How an assembly runs its content, when it is not the automatic choice. */
export const ASSEMBLY_MODES = {
  chain: "chain, in order",
  parallel: "parallel",
  mda: "MDA",
};

/**
 * @typedef {object} NodeAppearance
 * @property {keyof typeof NODE_ICON_PATHS} icon
 * @property {string} label - The kind, in words.
 * @property {string} tone - The color family: "component", "assembly" or "driver-<kind>".
 */

/**
 * How a node looks: its icon, the label of its kind and its color family.
 *
 * @param {{type: string, kind?: string, mode?: string}} node
 * @returns {NodeAppearance}
 */
export function nodeAppearance(node) {
  if (node.type === "assembly") {
    const mode = ASSEMBLY_MODES[/** @type {keyof typeof ASSEMBLY_MODES} */ (node.mode)];
    return { icon: "assembly", label: mode ? `${KIND_LABELS.assembly} · ${mode}` : KIND_LABELS.assembly, tone: "assembly" };
  }
  const kind = /** @type {keyof typeof NODE_ICON_PATHS} */ (node.kind ?? "");
  if (node.type === "driver") {
    const known = kind in NODE_ICON_PATHS;
    return {
      icon: known ? kind : "optimization",
      label: KIND_LABELS[/** @type {keyof typeof KIND_LABELS} */ (kind)] ?? "Driver",
      tone: `driver-${known ? kind : "optimization"}`,
    };
  }
  return {
    icon: kind in NODE_ICON_PATHS ? kind : "python_class",
    label: KIND_LABELS[/** @type {keyof typeof KIND_LABELS} */ (kind)] ?? "Component",
    tone: "component",
  };
}

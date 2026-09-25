// @ts-check
// Quality charts of a surrogate (SPEC § 7.4): predicted against observed values,
// and the histogram of the residuals. A perfect model puts every point on the
// diagonal and every residual at zero.
import { MARGIN, cssColor, drawAxes, formatNumber } from "../../charts/axis.js";
import { hideTooltip, showTooltip } from "../../charts/tooltip.js";
import { finite, linearDomain } from "../../lib/chart_scales.js";

const WIDTH = 380;
const HEIGHT = 300;
const BINS = 20;

/** @returns {any} */
function d3() {
  return /** @type {any} */ (window).d3;
}

/**
 * Pairs of finite observed and predicted values.
 *
 * @param {(number | null)[]} observed
 * @param {(number | null)[]} predicted
 * @returns {[number, number][]}
 */
function pairs(observed, predicted) {
  /** @type {[number, number][]} */
  const found = [];
  observed.forEach((value, index) => {
    const other = predicted[index];
    if (typeof value === "number" && typeof other === "number" && Number.isFinite(value) && Number.isFinite(other)) {
      found.push([value, other]);
    }
  });
  return found;
}

/**
 * An SVG with its plotting area.
 *
 * @param {HTMLElement} container
 * @param {string} title
 */
function frame(container, title) {
  const svg = d3()
    .select(container)
    .append("svg")
    .attr("class", "chart")
    .attr("width", WIDTH)
    .attr("height", HEIGHT)
    .attr("aria-label", title);
  const width = WIDTH - MARGIN.left - MARGIN.right;
  const height = HEIGHT - MARGIN.top - MARGIN.bottom;
  const plot = svg.append("g").attr("transform", `translate(${MARGIN.left},${MARGIN.top})`);
  return { plot, width, height };
}

/**
 * Draw predicted against observed values, with the diagonal.
 *
 * @param {HTMLElement} container
 * @param {{observed: (number | null)[], predicted: (number | null)[], label: string}} data
 */
export function drawPredictedVsObserved(container, { observed, predicted, label }) {
  const points = pairs(observed, predicted);
  const { plot, width, height } = frame(container, `Predicted against observed ${label}`);
  // Both axes share the domain, so that the diagonal is at 45°.
  const domain = linearDomain(points.flat());
  const x = d3().scaleLinear().domain(domain).range([0, width]).nice();
  const y = d3().scaleLinear().domain(x.domain()).range([height, 0]);
  drawAxes(plot, x, y, { width, height, xLabel: `Observed ${label}`, yLabel: `Predicted ${label}` });
  const [low, high] = x.domain();
  plot
    .append("line")
    .attr("class", "chart-diagonal")
    .attr("x1", x(low))
    .attr("y1", y(low))
    .attr("x2", x(high))
    .attr("y2", y(high))
    .attr("stroke", cssColor("--color-text-muted"))
    .attr("stroke-dasharray", "4 3");
  plot
    .append("g")
    .selectAll("circle")
    .data(points)
    .join("circle")
    .attr("class", "chart-point")
    .attr("cx", (/** @type {[number, number]} */ point) => x(point[0]))
    .attr("cy", (/** @type {[number, number]} */ point) => y(point[1]))
    .attr("r", 3)
    .attr("fill", cssColor("--color-accent"))
    .attr("fill-opacity", 0.7)
    .on("mousemove", (/** @type {MouseEvent} */ event, /** @type {[number, number]} */ point) =>
      showTooltip(event.clientX, event.clientY, [
        `Observed: ${formatNumber(point[0])}`,
        `Predicted: ${formatNumber(point[1])}`,
        `Error: ${formatNumber(point[1] - point[0])}`,
      ]),
    )
    .on("mouseleave", hideTooltip);
}

/**
 * Draw the histogram of the residuals (predicted minus observed).
 *
 * @param {HTMLElement} container
 * @param {{observed: (number | null)[], predicted: (number | null)[], label: string}} data
 */
export function drawResiduals(container, { observed, predicted, label }) {
  const residuals = finite(pairs(observed, predicted).map(([value, other]) => other - value));
  const { plot, width, height } = frame(container, `Residuals of ${label}`);
  const x = d3().scaleLinear().domain(linearDomain(residuals)).range([0, width]).nice(BINS);
  const bins = d3().bin().domain(x.domain()).thresholds(x.ticks(BINS))(residuals);
  const y = d3()
    .scaleLinear()
    .domain([0, d3().max(bins, (/** @type {any[]} */ bin) => bin.length) || 1])
    .range([height, 0])
    .nice();
  drawAxes(plot, x, y, { width, height, xLabel: `Predicted − observed ${label}`, yLabel: "Samples", integerX: false });
  plot
    .append("g")
    .selectAll("rect")
    .data(bins)
    .join("rect")
    .attr("class", "chart-bar")
    .attr("x", (/** @type {any} */ bin) => x(bin.x0) + 1)
    .attr("y", (/** @type {any[]} */ bin) => y(bin.length))
    .attr("width", (/** @type {any} */ bin) => Math.max(0, x(bin.x1) - x(bin.x0) - 1))
    .attr("height", (/** @type {any[]} */ bin) => height - y(bin.length))
    .attr("fill", cssColor("--color-driver-doe"))
    .on("mousemove", (/** @type {MouseEvent} */ event, /** @type {any} */ bin) =>
      showTooltip(event.clientX, event.clientY, [`${formatNumber(bin.x0)} to ${formatNumber(bin.x1)}`, `${bin.length} samples`]),
    )
    .on("mouseleave", hideTooltip);
}

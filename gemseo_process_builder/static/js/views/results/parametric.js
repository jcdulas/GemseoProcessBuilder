// @ts-check
// Parametric study views: a curve per response for one varied variable,
// a heat map with contour lines for two.
import { MARGIN, cssColor, drawAxes, formatNumber, seriesColor } from "../../charts/axis.js";
import { LineChart } from "../../charts/line_chart.js";
import { hideTooltip, showTooltip } from "../../charts/tooltip.js";
import { el } from "../../components/dom.js";
import { linearDomain } from "../../lib/chart_scales.js";
import { gridFromSamples, resample } from "../../lib/grid_from_samples.js";
import { choice, explain, labelled } from "./common.js";

export class ParametricView {
  /** @param {HTMLElement} root */
  constructor(root) {
    this.toolbar = el("div.results-toolbar");
    this.plot = el("div.parametric-plot");
    root.append(this.toolbar, this.plot);
    this.response = "";
    /** @type {import("./source.js").ResultsSource | null} */
    this.source = null;
    this.token = 0;
    new ResizeObserver(() => this.source && this.draw()).observe(this.plot);
  }

  /** @param {import("./source.js").ResultsSource} source */
  update(source) {
    this.source = source;
    if (source.live) {
      explain(this.plot, "The parametric views are available when the run ends.");
      this.toolbar.replaceChildren();
      return;
    }
    const outputs = [...source.byRole("output"), ...source.byRole("objective"), ...source.byRole("observable")].map((c) => c.name);
    this.response = outputs.includes(this.response) ? this.response : (outputs[0] ?? "");
    this.toolbar.replaceChildren(
      labelled(
        "Response",
        choice(outputs, this.response, (value) => {
          this.response = value;
          this.draw();
        }),
      ),
    );
    this.draw();
  }

  async draw() {
    const source = this.source;
    if (!source || source.live) {
      return;
    }
    const inputs = source.byRole("design variable").map((column) => column.name);
    if (!inputs.length || inputs.length > 2) {
      explain(this.plot, "Parametric views need one or two varied variables.");
      return;
    }
    const token = ++this.token;
    const outputs = [...source.byRole("output"), ...source.byRole("objective"), ...source.byRole("observable")].map((c) => c.name);
    const data = await source.matrix([...inputs, ...outputs]);
    if (token !== this.token) {
      return;
    }
    if (inputs.length === 1) {
      this.drawCurves(inputs[0], outputs, data);
    } else {
      this.drawHeatMap(inputs[0], inputs[1], data);
    }
  }

  /**
   * One curve per response against the varied variable.
   *
   * @param {string} input
   * @param {string[]} outputs
   * @param {any} data
   */
  drawCurves(input, outputs, data) {
    this.plot.replaceChildren();
    const chart = new LineChart(this.plot);
    const xs = data.columns[input];
    const order = xs.map((/** @type {number} */ _, /** @type {number} */ index) => index).sort((/** @type {number} */ a, /** @type {number} */ b) => xs[a] - xs[b]);
    chart.update({
      title: `Responses against ${input}`,
      xLabel: input,
      series: outputs.map((name, index) => ({
        name,
        color: seriesColor(index),
        points: order.map((/** @type {number} */ position) => ({ x: xs[position], y: data.columns[name][position] })),
      })),
    });
  }

  /**
   * A heat map of the chosen response over the grid of the two variables,
   * with contour lines.
   *
   * @param {string} xName
   * @param {string} yName
   * @param {any} data
   */
  drawHeatMap(xName, yName, data) {
    const d3 = /** @type {any} */ (window).d3;
    const grid = gridFromSamples(data.columns[xName], data.columns[yName], data.columns[this.response] ?? []);
    this.plot.replaceChildren();
    const width = this.plot.clientWidth;
    const height = this.plot.clientHeight;
    if (width < 160 || height < 120 || !grid.x.length || !grid.y.length) {
      return;
    }
    const innerWidth = width - MARGIN.left - MARGIN.right - 70;
    const innerHeight = height - MARGIN.top - MARGIN.bottom;
    const x = d3.scaleBand().domain(grid.x).range([0, innerWidth]).padding(0);
    const y = d3.scaleBand().domain(grid.y).range([innerHeight, 0]).padding(0);
    const values = grid.values.flat();
    const domain = linearDomain(values);
    const color = d3.scaleSequential(d3.interpolateRgb(cssColor("--color-accent-soft"), cssColor("--color-driver-optimization"))).domain(domain);
    const svg = d3.select(this.plot).append("svg").attr("width", width).attr("height", height);
    const group = svg.append("g").attr("transform", `translate(${MARGIN.left},${MARGIN.top})`);
    const cells = grid.y.flatMap((yValue, j) => grid.x.map((xValue, i) => ({ xValue, yValue, value: grid.values[j][i] })));
    group
      .selectAll("rect.heat-cell")
      .data(cells)
      .join("rect")
      .attr("class", "heat-cell")
      .attr("x", (/** @type {any} */ cell) => x(cell.xValue))
      .attr("y", (/** @type {any} */ cell) => y(cell.yValue))
      .attr("width", x.bandwidth())
      .attr("height", y.bandwidth())
      .attr("fill", (/** @type {any} */ cell) => (cell.value === null ? cssColor("--color-surface-alt") : color(cell.value)))
      .on("mousemove", (/** @type {MouseEvent} */ event, /** @type {any} */ cell) =>
        showTooltip(event.clientX, event.clientY, [
          `${xName} = ${formatNumber(cell.xValue)}, ${yName} = ${formatNumber(cell.yValue)}`,
          `${this.response}: ${cell.value === null ? "not evaluated" : formatNumber(cell.value)}`,
        ]),
      )
      .on("mouseleave", hideTooltip);
    // Contour lines between the cell centers, when every cell has a value:
    // on a finer grid interpolated from the samples, so they are smooth.
    if (grid.x.length > 1 && grid.y.length > 1 && values.every((value) => value !== null)) {
      const fine = resample(/** @type {number[][]} */ (grid.values), 12);
      const contours = d3.contours().size([fine.width, fine.height]).thresholds(8)(fine.values);
      const left = x.bandwidth() / 2;
      const bottom = innerHeight - y.bandwidth() / 2;
      const scaleX = (innerWidth - x.bandwidth()) / (fine.width - 1);
      const scaleY = (innerHeight - y.bandwidth()) / (fine.height - 1);
      const transform = d3.geoTransform({
        point(/** @type {number} */ px, /** @type {number} */ py) {
          // Fine grid coordinates (value k at k + 0.5) to pixels; y points up.
          const cx = Math.min(Math.max(px - 0.5, 0), fine.width - 1);
          const cy = Math.min(Math.max(py - 0.5, 0), fine.height - 1);
          // @ts-ignore - d3 binds `this` to the stream.
          this.stream.point(left + cx * scaleX, bottom - cy * scaleY);
        },
      });
      group
        .append("g")
        .attr("class", "contours")
        .selectAll("path")
        .data(contours)
        .join("path")
        .attr("class", "contour-line")
        .attr("d", d3.geoPath(transform));
    }
    const xAxis = d3.scaleLinear().domain(linearDomain(grid.x)).range([x.bandwidth() / 2, innerWidth - x.bandwidth() / 2]);
    const yAxis = d3.scaleLinear().domain(linearDomain(grid.y)).range([innerHeight - y.bandwidth() / 2, y.bandwidth() / 2]);
    drawAxes(group, xAxis, yAxis, { width: innerWidth, height: innerHeight, xLabel: xName, yLabel: yName });
    // Color legend.
    const legend = svg.append("g").attr("transform", `translate(${MARGIN.left + innerWidth + 24},${MARGIN.top})`);
    const steps = d3.range(0, 1.0001, 0.1);
    legend
      .selectAll("rect")
      .data(steps)
      .join("rect")
      .attr("y", (/** @type {number} */ step) => (1 - step) * (innerHeight - 10))
      .attr("width", 14)
      .attr("height", innerHeight / steps.length)
      .attr("fill", (/** @type {number} */ step) => color(domain[0] + step * (domain[1] - domain[0])));
    legend.append("text").attr("class", "chart-label").attr("x", 18).attr("y", 10).text(formatNumber(domain[1]));
    legend.append("text").attr("class", "chart-label").attr("x", 18).attr("y", innerHeight).text(formatNumber(domain[0]));
    legend.append("text").attr("class", "chart-label").attr("x", 0).attr("y", -8).text(this.response);
  }
}

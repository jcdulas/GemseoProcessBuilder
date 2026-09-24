// @ts-check
// Placeholder page: proves that ES modules, the vendored d3 and the bridge work.
import { connect } from "./bridge.js";
import { greeting } from "./lib/hello.js";

const d3 = /** @type {any} */ (window).d3;
const width = 480;
const height = 200;

const svg = d3
  .select("#stage")
  .append("svg")
  .attr("width", width)
  .attr("height", height)
  .attr("viewBox", `0 0 ${width} ${height}`);

svg
  .append("circle")
  .attr("class", "hello-circle")
  .attr("cx", width / 2)
  .attr("cy", height / 2)
  .attr("r", 90);

const label = svg
  .append("text")
  .attr("class", "hello-text")
  .attr("x", width / 2)
  .attr("y", height / 2)
  .text(greeting(`d3 ${d3.version}`));

const api = await connect();
const { version } = await api.call("app.version");
label.text(greeting(`Python ${version}`));
console.info(`Page ready: d3 ${d3.version}, application ${version}`);

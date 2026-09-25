/**
 * Linking the variables of two components at once, from the link panel of the
 * canvas: for each input of the target, the output of the source feeding it.
 * Pure: tested with node.
 */

/**
 * @typedef {{id: string, source: {node: string, port: string}, target: {node: string, port: string}}} StoredLink
 */

/**
 * The output of the source linked to each input of the target: explicit links
 * first, then outputs with the same name (couplings by name).
 * @param {StoredLink[]} links - The explicit links of the project.
 * @param {string} source
 * @param {string} target
 * @param {string[]} inputs - The inputs of the target.
 * @param {string[]} outputs - The outputs of the source.
 * @returns {Record<string, {output: string, explicit: boolean, other: string}>} By
 *   input; ``other`` names the node of an explicit link from another node.
 */
export function currentMapping(links, source, target, inputs, outputs) {
  const mapping = {};
  for (const input of inputs) {
    const link = links.find((candidate) => candidate.target.node === target && candidate.target.port === input);
    if (link && link.source.node === source) {
      mapping[input] = { output: link.source.port, explicit: true, other: "" };
    } else if (link) {
      mapping[input] = { output: "", explicit: true, other: link.source.node };
    } else {
      mapping[input] = { output: outputs.includes(input) ? input : "", explicit: false, other: "" };
    }
  }
  return mapping;
}

/**
 * The commands applying the choices of the panel.
 * @param {StoredLink[]} links
 * @param {string} source
 * @param {string} target
 * @param {Record<string, {output: string, explicit: boolean, other: string}>} before - From ``currentMapping``.
 * @param {Record<string, string>} chosen - The output chosen for each input ("" for none).
 * @returns {object[]} ``deleteLinks`` then ``addLink`` commands; empty when nothing changes.
 */
export function mappingCommands(links, source, target, before, chosen) {
  const deleted = [];
  const added = [];
  for (const [input, output] of Object.entries(chosen)) {
    const previous = before[input];
    if (!previous || output === previous.output) {
      continue;
    }
    // The explicit link feeding the input goes: an input has one source.
    const existing = links.find((link) => link.target.node === target && link.target.port === input);
    if (existing) {
      deleted.push(existing.id);
    }
    // Same name and no explicit link before: the coupling by name is enough.
    if (output && !(output === input && !previous.explicit && !existing)) {
      added.push({ type: "addLink", source: { node: source, port: output }, target: { node: target, port: input } });
    }
  }
  return [...(deleted.length ? [{ type: "deleteLinks", ids: deleted }] : []), ...added];
}

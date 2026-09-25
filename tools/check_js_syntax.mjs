// Parse every module of the page: a syntax error in one of them (a variable
// declared twice…) stops the whole page from loading, and the unit tests only
// import the pure modules of `lib/`. Run by tools/check.py with
// --experimental-vm-modules.
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { SourceTextModule } from "node:vm";

const root = new URL("../gemseo_process_builder/static/js/", import.meta.url);

/** @param {string} folder */
function modules(folder) {
  return readdirSync(folder, { withFileTypes: true }).flatMap((entry) => {
    const path = join(folder, entry.name);
    return entry.isDirectory() ? modules(path) : entry.name.endsWith(".js") ? [path] : [];
  });
}

const folder = root.pathname.replace(/^\/([A-Za-z]:)/, "$1");
let failures = 0;
for (const path of modules(folder)) {
  try {
    new SourceTextModule(readFileSync(path, "utf-8"), { identifier: path });
  } catch (error) {
    failures += 1;
    console.error(`${relative(folder, path)}: ${error}`);
  }
}
console.log(failures ? `${failures} modules do not parse` : "Every module parses");
process.exit(failures ? 1 : 0);

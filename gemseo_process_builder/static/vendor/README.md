# Vendored JavaScript libraries

These files are committed unmodified so that the application works offline (SPEC § 1.2, § 14.5). Their licenses are in [LICENSES/](LICENSES/) and must stay compatible with the project's MIT license (SPEC § 14.6).

| File | Library | Version | License | Source |
|---|---|---|---|---|
| `d3.v7.min.js` | [d3](https://d3js.org) | 7.9.0 | ISC ([LICENSES/d3-LICENSE.txt](LICENSES/d3-LICENSE.txt)) | https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js |
| `elk.bundled.js` | [elkjs](https://github.com/kieler/elkjs) | 0.12.0 | EPL-2.0 (dual EPL-2.0 / GPL-3.0-or-later upstream; used under EPL-2.0) ([LICENSES/elkjs-LICENSE.md](LICENSES/elkjs-LICENSE.md)) | https://cdn.jsdelivr.net/npm/elkjs@0.12.0/lib/elk.bundled.js |

`qwebchannel.js` is not stored here: it is read from Qt's resources and served at `vendor/qwebchannel.js` by the scheme handler.

Both libraries are UMD builds loaded with classic `<script>` tags; ES modules use them through `window.d3` and `window.ELK`.

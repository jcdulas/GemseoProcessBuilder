# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- A modern interface, close to n8n:
  - a top bar with the application menu, the state of the project and a prominent Run button;
  - an icon rail opening the panels, which float as rounded cards;
  - cards with colored icons on a dotted canvas, with run states (a pulsing ring, then a check);
  - toasts when a project is saved, a model is valid or a run ends;
  - the Inter font.
- The native menu bar is replaced by the menu of the top bar. The bottom panel is closed by default.
- Drivers are tiles of the workflow, next to the nodes they drive, instead of containers around them. Their links form a loop: the design variables go out, the objectives, constraints and responses come back. Dragging from a driver onto a node puts the node under its control.

### Added

- Wing sizing example: three coupled analytic disciplines under an optimizer.
- Beam chain example: an assembly run as a chain, in order, under a DOE.

### Fixed

- The surrogate wizard enables Next as soon as its step has loaded.

## [0.1.0]

First public release.

### Added

- Workflow canvas (SVG, d3): components as cards, one link per pair of nodes, a panel showing the variables of both sides of a link, hierarchical navigation, containers expanded in place, minimap, search, auto-layout (elkjs in a Web Worker), undo and redo.
- Components: analytic expressions, Python functions, GEMSEO discipline classes, executable wrappers of external codes, surrogate models; catalog folders scanned in a subprocess.
- Linking by name and by explicit links, isolated namespaces, units checked and converted with pint, N-D arrays flattened when needed.
- Assemblies (auto, chain, parallel, MDA) and drivers: MDA, DOE, optimization (MDF, IDF, DisciplinaryOpt, BiLevel), parametric study, nested drivers with their interface.
- Continuous validation with quick fixes, and a dry run of the generated script.
- Readable GEMSEO scripts exported from a model or a driver.
- Runs in separate processes with live progress, stop and kill; run history kept with each project.
- Results: summary, history, table, scatter matrix, XY plot, parallel coordinates, parametric views, run comparison, GEMSEO post-processings.
- N2 and XDSM views.
- Graphical editor of executable wrappers, with sample files, suggested output rules and test runs; reusable wrapper descriptors.
- Surrogate wizard: GEMSEO regression models, cross-validated quality, predicted-vs-observed charts.
- Exports: images (SVG, PNG) of every view, project report (HTML, PDF).
- Autosave and recovery, read-only opening of projects open elsewhere, atomic file writes, non-blocking dialogs for unexpected errors.
- Benchmarks of the performance targets on a 2,000-component, 50,000-variable model.

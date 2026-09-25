# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- Default values of more than 1,000 elements are no longer copied into the project: their ports keep their shape and type.
- Every name SymPy reads as a function or a constant (`gamma`, `beta`, `test`…), not only `S`, `N`, `E`, `I`, `O` and `Q`, is refused as a variable of a formula.
- A modern interface, close to n8n:
  - a top bar with the application menu, the state of the project and a prominent Run button;
  - an icon rail opening the panels, which float as rounded cards;
  - cards with colored icons on a dotted canvas, with run states (a pulsing ring, then a check);
  - toasts when a project is saved, a model is valid or a run ends;
  - the Inter font.
- The native menu bar is replaced by the menu of the top bar. The bottom panel is closed by default.
- Drivers have a card with the icon of their kind, like the other nodes, and can be steps of a sequence. Dragging from a driver onto a node puts the node under its control.

### Added

- NumPy arrays in the Python classes written from the inspector: each input has a shape, a type (float, int, complex) and a default value filling it; the classes use GEMSEO's simple grammar, which accepts matrices and checks data 30 times faster than a JSON grammar.
- Fast mode of a driver (Execution tab): GEMSEO does not check the data the disciplines exchange.
- Python classes written from the inspector: New Python file… writes a GEMSEO discipline class with its inputs and outputs, a table edits them in the class, Open in editor opens the file in your code editor (a new Code editor preference), and saving the file updates the component.
- Algorithms explained: what each optimization algorithm, sampling method and formulation does, when to use it and what it costs; a comparison of all of them; the algorithm suggested for an optimization problem, and why; tips in the design variables, objectives and constraints tabs.
- Guidance: the steps to set up a driver at the top of its editor, with a button for each; pickers say why they offer nothing; the formulas of an Analytic component have examples, completion (Tab), the list of functions and operators, and the inputs and outputs they define.
- Response surface in the results: a response over two design variables predicted by Kriging, a neural network, radial basis functions or a quadratic polynomial, in 2D or 3D, with the constraint boundaries and the infeasible regions.
- Results of large runs: a filter shared by the views keeps the design variables the response is most sensitive to, those with the largest gradients or those at a bound, and the active and violated constraints; the runner also saves the results in binary (`dataset.npy`), read 40 times faster.
- Derivatives: the origin of the derivatives of each component on its card (exact, approximated, none), Check derivatives on any node (GEMSEO's derivatives against finite differences, through the whole process for a driver), and a Gradients view in the results.
- Developer tools of the page: F12, Tools › Developer tools, or a right click where no other menu opens.
- NLopt optimization algorithms (MMA, SLSQP, COBYLA, BOBYQA, NEWUOA, BFGS), through the `nlopt` package.
- Start and end of the workflow: every level shows its inputs (whose values are typed once, for every node using them) and its results (the outputs no node uses, and the ones chosen).
- Execution arrows: the nodes of a chain are numbered and linked by arrows, and a chain is reordered by dragging an arrow from a node to the one that must run next. Parallel blocks show a fork and a join. A node running before the results it uses is an error. In a group run automatically, drawing an arrow makes it a chain, so an optimizer can be a step of a sequence.
- Optimization sequence example: material data, then the optimization of a beam, then its cost.
- Wing sizing example: three coupled analytic disciplines under an optimizer.
- Beam chain example: an assembly run as a chain, in order, under a DOE.

### Fixed

- The surrogate wizard enables Next as soon as its step has loaded.

## [0.1.0]

First public release.

### Added

- Derivatives: the origin of the derivatives of each component on its card (exact, approximated, none), Check derivatives on any node (GEMSEO's derivatives against finite differences, through the whole process for a driver), and a Gradients view in the results.
- Start and end of the workflow: every level shows its inputs (whose values are typed once, for every node using them) and its results (the outputs no node uses, and the ones chosen).
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

# Implementation plans

Each file `NN.md` is the detailed plan of one activity. Plans are completed **sequentially**, in numeric order; each one ends with a working, tested application. The completion protocol is described in [CLAUDE.md](../CLAUDE.md).

Every plan has the same structure: status, dependencies, SPEC references, goal, scope (in / out), deliverables, ordered steps, tests, acceptance criteria, and a free "Implementation notes" section filled in when the plan is done.

| # | Title | Depends on | SPEC |
|---|---|---|---|
| [00](00.md) | Repository bootstrap and tooling | — | § 3.6, 14.5, 15 |
| [01](01.md) | Qt shell and `gpb://` scheme | 00 | § 3.1, 3.2 |
| [02](02.md) | QWebChannel bridge | 01 | § 3.4 |
| [03](03.md) | HTML application shell and preferences | 02 | § 8.1, 8.8, 8.9 |
| [04](04.md) | Project model and file format | 03 | § 4 |
| [05](05.md) | Commands, undo/redo and document sync | 04 | § 3.5, 8.2 |
| [06](06.md) | Workflow canvas core | 05 | § 8.2 |
| [07](07.md) | Model tree and inspector | 06 | § 8.3, 8.7 |
| [08](08.md) | Worker infrastructure | 02 | § 3.1, 14.2, 14.3 |
| [09](09.md) | Component catalog and library panel | 07, 08 | § 7.6 |
| [10](10.md) | Components and introspection | 09 | § 7.1–7.3 |
| [11](11.md) | Coupling resolver | 10 | § 5.1–5.4 |
| [12](12.md) | Link editing on the canvas | 11 | § 5, 8.2 |
| [13](13.md) | Static validation and Problems panel | 12 | § 9.1, 8.8 |
| [14](14.md) | Code generation core | 13 | § 10 |
| [15](15.md) | Driver configuration and generated forms | 14 | § 6.2, 6.4, 8.6 |
| [16](16.md) | Scenario code generation and dry run | 15 | § 6.2, 9.2, 10 |
| [17](17.md) | Runner and run manager | 16 | § 11.1–11.4 |
| [18](18.md) | Live run monitoring | 17 | § 11.5 |
| [19](19.md) | Results storage and Runs panel | 17 | § 12.1, 8.8 |
| [20](20.md) | Results views I: summary, history, table | 18, 19 | § 12.2 |
| [21](21.md) | Results views II: scatter, parallel coordinates, parametric, compare | 20 | § 12.2 |
| [22](22.md) | Native GEMSEO post-processings | 15, 19 | § 12.3 |
| [23](23.md) | Nested drivers, BiLevel and local parallelism | 17 | § 6.1–6.3 |
| [24](24.md) | N2 view | 11 | § 8.4 |
| [25](25.md) | XDSM view | 16 | § 8.5 |
| [26](26.md) | Canvas ergonomics: minimap, search, auto-layout, grouping | 12 | § 8.2, 8.9 |
| [27](27.md) | Units and variable types | 14 | § 5.5, 5.6 |
| [28](28.md) | Executable wrapper runtime | 14 | § 7.5 |
| [29](29.md) | Executable wrapper editor | 28 | § 7.5 |
| [30](30.md) | Surrogates | 16, 19 | § 7.4 |
| [31](31.md) | Image export and report | 21, 24, 25 | § 13 |
| [32](32.md) | Large-model performance | 31 | § 14.1 |
| [33](33.md) | Robustness, packaging and documentation | 32 | § 14.2–14.5 |
| [34](34.md) | Modern interface | 33 | § 8.1, 8.2 |
| [35](35.md) | Drivers as tiles of the workflow | 34 | § 6.2, 8.2 |
| [36](36.md) | Execution arrows and chains built with arrows | 35 | § 6.1, 8.2 |
| [37](37.md) | Start and end of a workflow | 36 | § 8.2 |
| [38](38.md) | Drivers back to containers | 37 | § 6.2, 8.2 |
| [39](39.md) | Derivatives | 38 | § 9.3, 12.2 |
| [40](40.md) | Response surfaces and large results | 39 | § 12.1, 12.2 |
| [41](41.md) | Guidance in the editors | 40 | § 6.4, 7.1 |
| [42](42.md) | Optimization guidance and algorithm guides | 41 | § 6.4 |
| [43](43.md) | Python classes written from the inspector | 42 | § 7.3 |
| [44](44.md) | Large NumPy arrays | 43 | § 6.4, 7.3 |
| [45](45.md) | Examples of components | 44 | § 7.0 |
| [46](46.md) | Reading GEMSEO scripts | 45 | § 4.2.1 |
| [47](47.md) | Projects saved as GEMSEO scripts | 46 | § 4.2.2 |
| [48](48.md) | The script alone is the project | 47 | § 4.2 |
| [49](49.md) | Hidden data of projects | 48 | § 4.2.3 |

The "Depends on" column gives the strict technical dependencies; the numeric order is the recommended order and always satisfies them.

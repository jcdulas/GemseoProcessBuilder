# Architecture study

The outer loop of a structural sizing, as a GEMSEO Process Builder project: which architecture of a fuselage barrel —
how many stringers on its crown and on its upper sides — gives the lightest sized structure?

`architecture_study.py` is written by the application from its project (`tools/build_examples.py`); open it from the
Demos of the Library, or run it on its own:

```
python architecture_study.py
```

It needs, in the Python of the runs, `gemseo_nastran` and the packages of its chain: `nastran_architecture`,
`nastran_loads` and `nastran_refmodels` (and through them `nastran_layout`, `nastran_lcs`, `nastran_ssa`,
`nastran_sv`). The Library notes the packages missing.

## The pattern

A parametric study makes the requested architecture parameters vary; each evaluation is a chain of four disciplines of
`gemseo_nastran`, taken from its section of the Library:

1. **TopologyPlanner** — `nastran_architecture` turns the requested parameters into a viable architecture: a request
   that breaks a design rule is adjusted to the nearest viable configuration (`adjusted`, `distance`), and the plan of
   the topology is written. The planner comes before the CAD: the producer builds what the planner made viable.
2. **ModelProducer** — the producer builds the finite-element model and its layout from the plan. Here it is the
   stand-in of `nastran_refmodels`, called as `nastran_refmodels:produce`; in a real study it is the parametric CAD of
   the aircraft, given to `ModelProducer` as a command, which also delivers its STEP. The delivery is checked against
   the plan by `nastran_layout`.
3. **LoadModel** — `nastran_loads` computes the simplified loads of the aircraft and applies them to the model, and
   applies them again with the structural mass of the sized model (the mass snowball).
4. **StructuralSizing** — the inner sizing of `gemseo_nastran`, warm-started from the nearest architecture already
   sized.

Two requests that snap to one architecture are planned, produced and sized once: the store of `gemseo_nastran` keeps
every request, plan, delivery, load and sizing (by default `gemseo_nastran_store` in the temporary folder; the input
`store_path` of the four disciplines chooses another). It is the cache of the study, across runs, processes and
crashes: a study run again on its store takes seconds. The study has no file cache of GEMSEO: two processes evaluate
its samples, and GEMSEO does not support an HDF5 cache in parallel on Windows.

## The study

The stringer counts of the crown and of the upper sides take the values 4 and 5: the four viable variants of the box of
the example of `gemseo_nastran` (`viable_variants` enumerates them with `nastran_architecture`). The responses are the
mass, `feasible` (1 or 0), the smallest reserve factor, the continuous mass, the adjustment and its distance, and the
obtained counts. The sizing is short (two bi-level cycles of ten iterations): the study shows the pattern, not a final
design.

## Expected results

Measured on 2026-10-13 (two processes, Windows, 12 cores): 3 min 53 s for the four architectures; 22 s run again on
its store, with the same results.

| Crown | Upper side | Mass (kg) | Smallest reserve factor |
|---|---|---|---|
| 4 | 4 | 325.8 | 0.016 |
| 4 | 5 | 321.9 | 0.016 |
| 5 | 4 | 323.8 | 0.016 |
| 5 | 5 | 320.2 | 0.016 |

None is feasible with so short a sizing (`feasible` 0). In the Results: the parametric view of the mass over the two
counts, the XY plot of the mass against a count colored by `feasible`, the table sorted by mass. With `nastran_view` in
the Python of the runs, the context menu of a row of the table or of a point of the XY plot opens the structure of that
architecture in 3D, or compares it with the one other evaluation selected.

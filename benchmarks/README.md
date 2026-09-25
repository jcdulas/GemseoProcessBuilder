# Benchmarks

The performance targets of SPEC § 14.1, measured on a synthetic model
(SPEC § 15.5). They are not tests: run them on demand and before each release,
and copy the table into the release notes.

```
python benchmarks/run.py
```

`run.py` generates the reference model (2,000 analytic components, 50,000
variables, 6 levels, a 300-component level and a fake run of 50,000 samples) in
a temporary folder, then:

- measures the pure Python parts in its own process (loading, resolution,
  validation, snapshot, N2 matrix);
- starts the application in benchmark mode
  (`python -m gemseo_process_builder MODEL --benchmark all`): the page opens the
  model and runs the scripted scenarios of `static/js/services/benchmark.js`
  (commands, validation round trip, canvas zoom and pan, N2 scrolling,
  auto-layout, results views), then reports its measurements and quits.

Keep the window of the application visible and the machine otherwise idle:
hidden windows get fewer frames, and other programs slow everything down.

Options: `--model FILE` measures another project, `--scenario NAME` runs one
scenario (`command`, `validation`, `canvas`, `n2`, `layout`, `results`), and
`--python-only` skips the application.

`generate.py` writes synthetic models on its own:

```
python benchmarks/generate.py model.gpb.json --components 500 --samples 1000
```

The results are written to `results/<date>.json`, with the machine they were
measured on.

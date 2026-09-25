# Research notebook

Each campaign gets a directory under `campaigns/`:

```text
campaigns/<campaign-id>/
  campaign.json       research question and title
  entries/*.json      timestamped plans, tool results, and notes
  notebook.md         readable view, refreshed whenever the notebook is used
```

The co-scientist writes these through its research tools. JSON entries are the
record; `notebook.md` is a generated view. Corrections are new notes, so earlier
conclusions remain visible. There is no database or separate notebook application.

The notebook links the existing immutable experiment/input snapshots in
`.agentic-design/experiments/`, job records in `.agentic-design/jobs/`, and outputs
in `results/`. Back up all four directories together. They are local and ignored
by Git; **committing the code does not back up research records**.

See [the co-scientist guide](../docs/co-scientist.md) to start, resume, or repeat work.

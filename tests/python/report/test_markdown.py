"""The Markdown of the Claude copilot, as HTML for the report."""

from gemseo_process_builder.report.markdown import markdown_to_html


def test_headings_paragraphs_and_lists() -> None:
    text = """# Result
The optimum is **feasible**; `c_1` is active.
It took 8 evaluations.

## Next
- Tighten `ftol_rel`
  to 1e-8.
- Try COBYLA.

1. First
2. Second
"""
    assert markdown_to_html(text) == (
        "<h4>Result</h4>"
        "<p>The optimum is <strong>feasible</strong>; <code>c_1</code> is active. "
        "It took 8 evaluations.</p>"
        "<h5>Next</h5>"
        "<ul><li>Tighten <code>ftol_rel</code> to 1e-8.</li><li>Try COBYLA.</li></ul>"
        "<ol><li>First</li><li>Second</li></ol>"
    )


def test_html_is_escaped() -> None:
    assert markdown_to_html("<script>alert(1)</script>") == (
        "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>"
    )


def test_tables() -> None:
    text = """Result:

| Quantity | Value |
|---|---|
| `obj` | 3.18 |
| c_1 | 0 |
Done.
"""
    assert markdown_to_html(text) == (
        "<p>Result:</p>"
        "<table><thead><tr><th>Quantity</th><th>Value</th></tr></thead>"
        "<tbody><tr><td><code>obj</code></td><td>3.18</td></tr>"
        "<tr><td>c_1</td><td>0</td></tr></tbody></table>"
        "<p>Done.</p>"
    )

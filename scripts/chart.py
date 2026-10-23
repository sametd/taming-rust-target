#!/usr/bin/env python3
"""Render the results as an inline SVG bar chart using the site's CSS variables."""
import json, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
rows = {r["name"]: r for r in json.load(open(ROOT / "results/summary.json"))}

ORDER = [
    ("baseline", "defaults"),
    ("no-incremental", "incremental = false"),
    ("link-zlib", "link: compress debug, zlib"),
    ("split-unpacked", 'split-debuginfo = "unpacked"'),
    ("link-zstd", "link: compress debug, zstd"),
    ("debug-line-tables", 'debug = "line-tables-only"'),
    ("deps-no-debug", "deps: debug = false"),
    ("single-test-binary", "one test binary"),
    ("deps-no-debug+unpacked", "global config only"),
    ("single+unpacked+link-zlib", "full debug info everywhere"),
    ("single+deps-no-debug+unpacked", "global config + one test binary"),
    ("nightly-recipe2+embed", "same, nightly embed-metadata"),
    ("single+line-tables+deps-none", "line tables, deps none, one binary"),
]
HIGHLIGHT = {"single+deps-no-debug+unpacked", "nightly-recipe2+embed"}
BROKEN = {"link-zstd"}

W, label_w, bar_w, row_h, top = 760, 250, 380, 28, 34
H = top + row_h * len(ORDER) + 14
maxv = max(rows[k]["gib"] for k, _ in ORDER)

out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="target/ size per configuration, GiB" '
       f'style="width:100%;height:auto;font-family:var(--font-mono);font-size:13px">']
out.append(f'<text x="{label_w}" y="18" fill="var(--fg-muted)" font-size="12">target/ after one dev session (GiB)</text>')
out.append(f'<text x="{W - 4}" y="18" fill="var(--fg-muted)" font-size="12" text-anchor="end">edit → rebuild tests</text>')
for i, (key, label) in enumerate(ORDER):
    r = rows[key]
    y = top + i * row_h
    w = max(2, bar_w * r["gib"] / maxv)
    color = "var(--accent)" if key in HIGHLIGHT else "var(--fg-muted)"
    opacity = "1" if key in HIGHLIGHT else "0.55"
    weight = ' font-weight="700"' if key in HIGHLIGHT else ""
    out.append(f'<text x="{label_w - 12}" y="{y + 15}" fill="var(--fg)" text-anchor="end"{weight}>{label}</text>')
    out.append(f'<rect x="{label_w}" y="{y + 3}" width="{w:.1f}" height="{row_h - 10}" rx="3" fill="{color}" fill-opacity="{opacity}"/>')
    note = " (no backtrace lines)" if key in BROKEN else ""
    out.append(f'<text x="{label_w + w + 8:.1f}" y="{y + 15}" fill="var(--fg)"{weight}>{r["gib"]:.2f}{note}</text>')
    out.append(f'<text x="{W - 4}" y="{y + 15}" fill="var(--fg-muted)" text-anchor="end">{r["edit"]:.1f} s</text>')
out.append("</svg>")
svg = "".join(out)
(ROOT / "results/chart.svg").write_text(svg)
print(f"{len(svg)} bytes")

"""Render the confidence-calibration plot the README requires (spec v2 §9.2, §13).

§13 asks for a reliability diagram in the README, and §9.2 explains why: almost no portfolio
project shows calibration, and a confidence score nobody has checked is decoration. This script
draws that diagram from the evaluation run's own JSON, so the picture cannot drift from the
numbers — regenerate it after any eval and it tells the truth or it fails loudly.

**Why hand-written SVG rather than matplotlib.** The plot is one chart. Adding a plotting stack to
draw it would grow the dependency surface of a project that has deliberately kept it small (§4's
argument against LangChain is the same argument), and a binary PNG diffs as an opaque blob in a
repository where every other artefact is reviewable text. SVG is text, versions cleanly, renders
inline on GitHub, and needs nothing installed.

The diagram is two panels — one per benchmark — because the finding worth showing is not either
curve on its own but that **they agree**: the 0.8-0.9 bin is overconfident on both, by +.181 and
+.252, which makes it a property of the judge rather than of one benchmark. A single panel would
bury that.

Bin counts are drawn on the plot deliberately. The hand-written set has 17 samples and one of its
bins holds a single verdict; a reliability diagram that hides its sample sizes invites a reader to
over-read exactly that kind of point.

Run::

    uv run python scripts/build_calibration_plot.py
"""

import json
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_RESULTS_ROOT = _REPO_ROOT / "benchmarks" / "results"
_OUTPUT = _REPO_ROOT / "docs" / "calibration.svg"

# --- Geometry, in SVG user units -------------------------------------------------------------
_PANEL = 290  # plot area, square: confidence and accuracy share a scale, so the diagonal is 45°
_PAD_LEFT = 56
_PAD_TOP = 46
_PAD_BETWEEN = 70
_PAD_BOTTOM = 74
_WIDTH = _PAD_LEFT * 2 + _PANEL * 2 + _PAD_BETWEEN
_HEIGHT = _PAD_TOP + _PANEL + _PAD_BOTTOM

# --- Colours ---------------------------------------------------------------------------------
# An explicit light background rather than transparency: GitHub renders README images against
# either theme, and a transparent plot with dark text vanishes in dark mode.
_BG = "#ffffff"
_INK = "#1f2328"
_MUTED = "#6e7781"
_GRID = "#e4e8ec"
_BAR = "#4c8dd9"
_BAR_OVER = "#d98324"  # bins where the judge is overconfident: confidence above accuracy
_DIAGONAL = "#8c959f"


@dataclass(frozen=True)
class Bin:
    """One reliability bin: how confident the judge was, and how often it was right."""

    lower: float
    upper: float
    count: int
    mean_confidence: float
    accuracy: float

    @property
    def gap(self) -> float:
        """Confidence minus accuracy. Positive means overconfident."""
        return self.mean_confidence - self.accuracy


@dataclass(frozen=True)
class Panel:
    """One benchmark's calibration."""

    name: str
    bins: list[Bin]
    expected_error: float
    sample_count: int


def latest_eval(results_root: Path) -> Path:
    """Return the newest ``eval.json`` under the results root.

    Runs are written to timestamped directories whose names sort chronologically, so the newest
    is the last one — no file mtimes involved, which keeps this stable across a fresh clone.

    Args:
        results_root: ``benchmarks/results``.

    Returns:
        Path to the most recent run's ``eval.json``.

    Raises:
        FileNotFoundError: If no run has been written yet.
    """
    runs = sorted(path for path in results_root.glob("*/eval.json"))
    if not runs:
        raise FileNotFoundError(f"no eval runs under {results_root}")
    return runs[-1]


def read_panels(eval_path: Path) -> list[Panel]:
    """Load each benchmark's grouped-granularity calibration from an eval run.

    ``grouped`` is the headline granularity — findings as displayed — so it is the one whose
    calibration a reader of the README is being asked to trust.

    Args:
        eval_path: An ``eval.json`` written by the evaluation runner.

    Returns:
        One panel per benchmark, in the order the run recorded them.
    """
    data = json.loads(eval_path.read_text(encoding="utf-8"))
    panels: list[Panel] = []
    for benchmark in data["benchmarks"]:
        calibration = benchmark["metrics"]["grouped"]["calibration"]
        panels.append(
            Panel(
                name=benchmark["name"],
                bins=[Bin(**bin_data) for bin_data in calibration["bins"]],
                expected_error=calibration["expected_error"],
                sample_count=calibration["sample_count"],
            )
        )
    return panels


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _panel_svg(panel: Panel, origin_x: int) -> list[str]:
    """Draw one panel: axes, the perfect-calibration diagonal, and a bar per populated bin."""
    top = _PAD_TOP
    bottom = top + _PANEL

    def x_of(value: float) -> float:
        return origin_x + value * _PANEL

    def y_of(value: float) -> float:
        return bottom - value * _PANEL

    parts: list[str] = [
        f'<text x="{origin_x}" y="{top - 22}" class="title">{_escape(panel.name)}</text>',
        f'<text x="{origin_x}" y="{top - 6}" class="sub">'
        f"ECE {panel.expected_error:.4f} · n={panel.sample_count}</text>",
    ]

    for tick in range(0, 11, 2):
        value = tick / 10
        parts.append(
            f'<line x1="{origin_x}" y1="{y_of(value):.1f}" x2="{origin_x + _PANEL}" '
            f'y2="{y_of(value):.1f}" class="grid"/>'
        )
        parts.append(
            f'<text x="{origin_x - 10}" y="{y_of(value) + 4:.1f}" class="tick-y">{value:.1f}</text>'
        )
        parts.append(
            f'<text x="{x_of(value):.1f}" y="{bottom + 18}" class="tick-x">{value:.1f}</text>'
        )

    # Perfect calibration: accuracy equals confidence.
    parts.append(
        f'<line x1="{x_of(0):.1f}" y1="{y_of(0):.1f}" x2="{x_of(1):.1f}" y2="{y_of(1):.1f}" '
        f'class="diagonal"/>'
    )

    # Opacity carries sample size. A bin holding one verdict must not look as solid as one
    # holding eighty-two: the hand-written set has exactly that problem, and a reliability
    # diagram whose bars hide their weight invites precisely the over-reading it should prevent.
    heaviest = max((item.count for item in panel.bins), default=1) or 1

    for item in panel.bins:
        if not item.count:
            continue
        left = x_of(item.lower) + 2
        width = (item.upper - item.lower) * _PANEL - 4
        height = max(item.accuracy * _PANEL, 1.0)
        colour = _BAR_OVER if item.gap > 0.05 else _BAR
        opacity = 0.35 + 0.50 * (item.count / heaviest)
        parts.append(
            f'<rect x="{left:.1f}" y="{y_of(item.accuracy):.1f}" width="{width:.1f}" '
            f'height="{height:.1f}" fill="{colour}" fill-opacity="{opacity:.2f}" rx="2"/>'
        )
        # Where the judge *said* it was, so the gap to the bar top is readable directly.
        parts.append(
            f'<circle cx="{x_of(item.mean_confidence):.1f}" cy="{y_of(item.mean_confidence):.1f}" '
            f'r="3.4" fill="{_BG}" stroke="{_INK}" stroke-width="1.4"/>'
        )
        # Labels flip inside the bar when it is too tall to caption from above, so nothing is
        # clipped by the frame — the 82-verdict bin reaches .915 and would lose its own count.
        centre = left + width / 2
        if item.accuracy > 0.86:
            # White reads well on a solid bar and disappears on a faint one, and opacity here
            # tracks sample size — so the lightest bars are exactly the ones needing dark text.
            inside = "count-in" if opacity >= 0.60 else "count-in-dark"
            parts.append(
                f'<text x="{centre:.1f}" y="{y_of(item.accuracy) + 14:.1f}" '
                f'class="{inside}">n={item.count}</text>'
            )
        else:
            parts.append(
                f'<text x="{centre:.1f}" y="{y_of(item.accuracy) - 7:.1f}" '
                f'class="count">n={item.count}</text>'
            )
        if abs(item.gap) >= 0.10:
            # Sign decides the colour. An underconfident bin drawn in the overconfident colour
            # would say the opposite of what happened.
            style = "gap-over" if item.gap > 0 else "gap-under"
            label_y = y_of(item.mean_confidence) - 9
            if item.mean_confidence > 0.93:
                label_y = y_of(item.mean_confidence) + 16
            parts.append(
                f'<text x="{centre:.1f}" y="{label_y:.1f}" class="{style}">{item.gap:+.2f}</text>'
            )

    parts.append(
        f'<rect x="{origin_x}" y="{top}" width="{_PANEL}" height="{_PANEL}" class="frame"/>'
    )
    parts.append(
        f'<text x="{origin_x + _PANEL / 2:.1f}" y="{bottom + 40}" class="axis">'
        f"Judge confidence</text>"
    )
    return parts


def render(panels: list[Panel]) -> str:
    """Render the full two-panel reliability diagram.

    Args:
        panels: One panel per benchmark; the first two are drawn.

    Returns:
        A complete, self-contained SVG document.
    """
    body: list[str] = []
    for index, panel in enumerate(panels[:2]):
        body.extend(_panel_svg(panel, _PAD_LEFT + index * (_PANEL + _PAD_BETWEEN)))

    legend_y = _HEIGHT - 18
    legend = [
        f'<rect x="{_PAD_LEFT}" y="{legend_y - 9}" width="11" height="11" fill="{_BAR_OVER}" '
        f'fill-opacity="0.82" rx="2"/>',
        f'<text x="{_PAD_LEFT + 17}" y="{legend_y}" class="legend">'
        f"overconfident (confidence exceeds accuracy by &gt;.05)</text>",
        f'<rect x="{_PAD_LEFT + 330}" y="{legend_y - 9}" width="11" height="11" fill="{_BAR}" '
        f'fill-opacity="0.82" rx="2"/>',
        f'<text x="{_PAD_LEFT + 347}" y="{legend_y}" class="legend">calibrated</text>',
        f'<circle cx="{_PAD_LEFT + 452}" cy="{legend_y - 4}" r="3.4" fill="{_BG}" '
        f'stroke="{_INK}" stroke-width="1.4"/>',
        f'<text x="{_PAD_LEFT + 462}" y="{legend_y}" class="legend">stated confidence</text>',
    ]

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{_WIDTH}" height="{_HEIGHT}"
     viewBox="0 0 {_WIDTH} {_HEIGHT}" role="img"
     aria-label="Reliability diagrams for the synthetic and hand-written benchmarks">
  <style>
    text {{ font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }}
    .title {{ font-size: 14px; font-weight: 600; fill: {_INK}; }}
    .sub {{ font-size: 11px; fill: {_MUTED}; }}
    .tick-x {{ font-size: 10px; fill: {_MUTED}; text-anchor: middle; }}
    .tick-y {{ font-size: 10px; fill: {_MUTED}; text-anchor: end; }}
    .axis {{ font-size: 11px; fill: {_MUTED}; text-anchor: middle; }}
    .count {{ font-size: 9px; fill: {_MUTED}; text-anchor: middle; }}
    .count-in {{ font-size: 9px; fill: #ffffff; text-anchor: middle; font-weight: 600; }}
    .count-in-dark {{ font-size: 9px; fill: {_INK}; text-anchor: middle; font-weight: 600; }}
    .gap-over {{ font-size: 10px; font-weight: 600; fill: {_BAR_OVER}; text-anchor: middle; }}
    .gap-under {{ font-size: 10px; font-weight: 600; fill: {_BAR}; text-anchor: middle; }}
    .legend {{ font-size: 10.5px; fill: {_MUTED}; }}
    .grid {{ stroke: {_GRID}; stroke-width: 1; }}
    .frame {{ fill: none; stroke: {_GRID}; stroke-width: 1; }}
    .diagonal {{ stroke: {_DIAGONAL}; stroke-width: 1.2; stroke-dasharray: 4 3; }}
    .ylab {{ font-size: 11px; fill: {_MUTED}; text-anchor: middle; }}
  </style>
  <rect width="{_WIDTH}" height="{_HEIGHT}" fill="{_BG}"/>
  <text x="18" y="{_PAD_TOP + _PANEL / 2:.1f}" class="ylab"
        transform="rotate(-90 18 {_PAD_TOP + _PANEL / 2:.1f})">Observed accuracy</text>
  {chr(10).join("  " + part for part in body)}
  {chr(10).join("  " + part for part in legend)}
</svg>
"""


def main() -> None:
    """Build the plot from the most recent evaluation run."""
    eval_path = latest_eval(_RESULTS_ROOT)
    panels = read_panels(eval_path)
    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT.write_text(render(panels), encoding="utf-8")

    print(f"read {eval_path.relative_to(_REPO_ROOT)}")
    for panel in panels:
        populated = [item for item in panel.bins if item.count]
        worst = max(populated, key=lambda item: item.gap)
        print(
            f"  {panel.name}: ECE {panel.expected_error:.4f}, n={panel.sample_count}, "
            f"worst bin [{worst.lower:.1f},{worst.upper:.1f}) gap {worst.gap:+.3f}"
        )
    print(f"wrote {_OUTPUT.relative_to(_REPO_ROOT)}")


if __name__ == "__main__":
    main()

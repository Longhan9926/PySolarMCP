from __future__ import annotations

import csv
import re
from pathlib import Path

from solarcell_sim.schema import Diagnostic, SimulationCurves, SimulationMetrics, TableRef
from solarcell_sim.storage import write_json

JV_COLUMNS = [
    "v(V)",
    "jtot(mA/cm2)",
    "j_total_rec(mA/cm2)",
    "j_total_gen(mA/cm2)",
    "jbulk(mA/cm2)",
    "jifr(mA/cm2)",
    "jminor_left(mA/cm2)",
    "jminor_right(mA/cm2)",
    "j_SRH(mA/cm2)",
    "j_Radiative(mA/cm2)",
    "j_Auger(mA/cm2)",
]


def _extract_value(text: str, label: str, unit: str) -> float | None:
    pattern = rf"{label}\s*=\s*([-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?)\s*{re.escape(unit)}"
    match = re.search(pattern, text)
    return float(match.group(1)) if match else None


def parse_scaps_iv_text(text: str) -> tuple[SimulationMetrics, list[list[float]], list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    metrics = SimulationMetrics(
        voc_v=_extract_value(text, "Voc", "Volt"),
        jsc_ma_cm2=_extract_value(text, "Jsc", "mA/cm2"),
        ff_percent=_extract_value(text, "FF", "%"),
        pce_percent=_extract_value(text, "eta", "%"),
        extrapolated=bool(re.search(r"(Voc|Jsc|FF|eta)\s*=.*\bextrapolated\b", text)),
    )

    missing = [
        name
        for name, value in (
            ("Voc", metrics.voc_v),
            ("Jsc", metrics.jsc_ma_cm2),
            ("FF", metrics.ff_percent),
            ("eta", metrics.pce_percent),
        )
        if value is None
    ]
    if missing:
        diagnostics.append(
            Diagnostic(
                severity="warning",
                code="parser.summary_missing",
                message=f"Missing SCAPS summary fields: {', '.join(missing)}",
            )
        )

    rows: list[list[float]] = []
    data_pattern = re.compile(
        r"^\s*"
        + r"\s+".join([r"([-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?)"] * len(JV_COLUMNS))
        + r"\s*$"
    )
    for line in text.splitlines():
        match = data_pattern.match(line)
        if match:
            rows.append([float(value) for value in match.groups()])

    if not rows:
        diagnostics.append(
            Diagnostic(severity="warning", code="parser.jv_curve_missing", message="No 11-column J-V curve rows were parsed")
        )
    return metrics, rows, diagnostics


def parse_scaps_iv_file(output_file: Path, parsed_dir: Path) -> tuple[SimulationMetrics, SimulationCurves, list[Diagnostic]]:
    text = output_file.read_text(encoding="ISO-8859-1")
    metrics, rows, diagnostics = parse_scaps_iv_text(text)
    parsed_dir.mkdir(parents=True, exist_ok=True)

    metrics_path = parsed_dir / "metrics.json"
    write_json(metrics_path, metrics.model_dump(mode="json", by_alias=True))

    table_ref: TableRef | None = None
    if rows:
        csv_path = parsed_dir / "jv.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(JV_COLUMNS)
            writer.writerows(rows)
        table_ref = TableRef(path=str(csv_path), columns=JV_COLUMNS, rows=len(rows))

    return metrics, SimulationCurves(jv=table_ref), diagnostics


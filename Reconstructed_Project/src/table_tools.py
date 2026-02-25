"""CSV inspection/transformation and chart helper utilities."""

from __future__ import annotations

import base64
import csv
import io
import os
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from file_mod_tools import resolve_file_path


def _detect_delimiter(sample: str, fallback: str = ",") -> str:
    try:
        return csv.Sniffer().sniff(sample).delimiter
    except Exception:
        return fallback


def _to_rows(path: str, delimiter: str | None, encoding: str) -> tuple[list[list[str]], str]:
    with open(path, "r", encoding=encoding, errors="replace", newline="") as fh:
        raw = fh.read()
    delim = delimiter or _detect_delimiter(raw[:4096])
    rows = list(csv.reader(io.StringIO(raw), delimiter=delim))
    return rows, delim


def inspect_csv(
    con,
    file_id: str,
    max_rows: int | None = None,
    max_bytes: int | None = None,
    delimiter: str | None = None,
    has_header: bool | None = None,
    encoding: str | None = None,
) -> dict[str, Any]:
    path, _meta, _conv_id = resolve_file_path(con, file_id)
    enc = encoding or "utf-8"
    rows, delim = _to_rows(path, delimiter, enc)
    limit = max(1, int(max_rows or 30))

    data_rows = rows
    header = None
    if has_header is True and rows:
        header = rows[0]
        data_rows = rows[1:]

    body = data_rows[:limit]
    return {
        "ok": True,
        "path": path,
        "delimiter": delim,
        "encoding": enc,
        "has_header": has_header,
        "rows_total": len(rows),
        "columns": max((len(r) for r in rows), default=0),
        "header": header,
        "preview": body,
        "max_bytes": max_bytes,
    }


def transform_csv(
    con,
    file_id: str,
    select_columns: list[str] | list[int] | None = None,
    filter_equals: dict[str, Any] | None = None,
    filter_contains: dict[str, str] | None = None,
    limit_rows: int | None = None,
    delimiter: str | None = None,
    encoding: str | None = None,
    output_mode: str = "sidecar",
    output_suffix: str = "-xform",
) -> dict[str, Any]:
    path, _meta, _conv_id = resolve_file_path(con, file_id)
    enc = encoding or "utf-8"
    rows, delim = _to_rows(path, delimiter, enc)
    if not rows:
        return {"ok": True, "path": path, "rows_in": 0, "rows_out": 0}

    header = rows[0]
    body = rows[1:] if header else []

    idx_map = {name: i for i, name in enumerate(header)}

    def row_match(row: list[str]) -> bool:
        if filter_equals:
            for k, v in filter_equals.items():
                i = idx_map.get(str(k))
                if i is None or i >= len(row) or str(row[i]) != str(v):
                    return False
        if filter_contains:
            for k, v in filter_contains.items():
                i = idx_map.get(str(k))
                if i is None or i >= len(row) or str(v).lower() not in str(row[i]).lower():
                    return False
        return True

    out_rows = [r for r in body if row_match(r)]
    if limit_rows:
        out_rows = out_rows[: max(1, int(limit_rows))]

    if select_columns:
        col_indices: list[int] = []
        for c in select_columns:
            if isinstance(c, int):
                if 0 <= c < len(header):
                    col_indices.append(c)
            else:
                i = idx_map.get(str(c))
                if i is not None:
                    col_indices.append(i)
        col_indices = sorted(set(col_indices))
        if col_indices:
            header_out = [header[i] for i in col_indices]
            out_rows = [[row[i] if i < len(row) else "" for i in col_indices] for row in out_rows]
        else:
            header_out = header
    else:
        header_out = header

    if output_mode == "overwrite":
        out_path = path
    else:
        root, ext = os.path.splitext(path)
        out_path = f"{root}{output_suffix or '-xform'}{ext}"

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding=enc, newline="") as fh:
        w = csv.writer(fh, delimiter=delim)
        if header_out:
            w.writerow(header_out)
        w.writerows(out_rows)

    return {
        "ok": True,
        "path_in": path,
        "path_out": out_path,
        "delimiter": delim,
        "rows_in": len(body),
        "rows_out": len(out_rows),
        "columns_out": len(header_out),
        "preview": out_rows[:20],
    }


def generate_chart(
    series: list[dict[str, Any]],
    kind: str = "bar",
    title: str | None = None,
    width: float | None = None,
    height: float | None = None,
) -> dict[str, Any]:
    if not isinstance(series, list) or not series:
        return {"ok": False, "error": "series must be a non-empty list"}

    fig, ax = plt.subplots(figsize=(width or 8, height or 4.5))
    labels = [str(s.get("label", "")) for s in series]
    values = [float(s.get("value", 0) or 0) for s in series]

    k = (kind or "bar").lower()
    if k == "line":
        ax.plot(labels, values, marker="o")
    elif k == "scatter":
        ax.scatter(labels, values)
    else:
        ax.bar(labels, values)

    ax.set_title(title or "Chart")
    ax.tick_params(axis="x", rotation=30)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    payload = base64.b64encode(buf.getvalue()).decode("ascii")

    return {
        "ok": True,
        "kind": k,
        "points": len(series),
        "image_base64": payload,
        "mime_type": "image/png",
    }

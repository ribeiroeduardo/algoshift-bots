#!/usr/bin/env python3
"""
Consolida vários CSVs de exportação TradingView num único ficheiro,
incluindo o consolidado anterior (se existir) para não perder histórico,
remove linhas duplicadas e arquiva só os CSVs novos (não o consolidado).

A dedupe considera números equivalentes após arredondamento (exportações
sobrepostas do TradingView às vezes diferem só na precisão dos floats).
"""
from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

DEFAULT_OUTPUT = "consolidado-tradingview.csv"
ENCODING = "utf-8-sig"
# Casas decimais para comparar valores numéricos (exportações sobrepostas podem diferir
# além da 8.ª casa, ex. P&L 74.7717646990 vs 74.7717646988 com 10 casas ainda “diferentes”)
DEFAULT_ROUND_DECIMALS = 8

# Célula que é só um número (saldos, P&L); não confundir com texto em Action
_NUM_CELL = re.compile(
    r"^\s*-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\s*$"
)


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding=ENCODING, newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return [], []
        fieldnames = list(reader.fieldnames)
        rows: list[dict[str, str]] = []
        for row in reader:
            rows.append({k: (row.get(k) or "").strip() for k in fieldnames})
        return fieldnames, rows


def merge_fieldnames(order: list[str], extra: list[str]) -> list[str]:
    seen = set(order)
    out = list(order)
    for name in extra:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _quantize_numeric_string(s: str, places: int) -> str:
    s = s.strip()
    if not s:
        return s
    try:
        d = Decimal(s)
        q = Decimal(10) ** -places
        rounded = d.quantize(q, rounding=ROUND_HALF_UP)
        t = format(rounded, "f")
        if "." in t:
            t = t.rstrip("0").rstrip(".")
        return t
    except InvalidOperation:
        return s


def _normalize_cell_for_dedupe(fieldname: str, value: str, places: int) -> str:
    v = (value or "").strip()
    if fieldname.strip().lower() == "time":
        return v
    if _NUM_CELL.match(v):
        return _quantize_numeric_string(v, places)
    return v


def row_key(
    fieldnames: list[str], row: dict[str, str], round_decimals: int
) -> tuple[str, ...]:
    return tuple(
        _normalize_cell_for_dedupe(k, row.get(k, ""), round_decimals)
        for k in fieldnames
    )


def _parse_time_sort(row: dict[str, str]) -> datetime:
    t = (row.get("Time") or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            continue
    return datetime.min


def dedupe_in_place(path: Path, dry: bool, round_decimals: int) -> int:
    """Remove linhas duplicadas num único CSV e regrava (ordem: Time mais recente primeiro)."""
    cols, rows = read_rows(path)
    if not cols:
        print("Erro: ficheiro vazio ou sem cabeçalho.", file=sys.stderr)
        return 1
    fieldnames = cols
    unique_rows: dict[tuple[str, ...], dict[str, str]] = {}
    for row in rows:
        full = {k: row.get(k, "") for k in fieldnames}
        key = row_key(fieldnames, full, round_decimals)
        if key not in unique_rows:
            unique_rows[key] = full
    out_list = list(unique_rows.values())
    out_list.sort(key=_parse_time_sort, reverse=True)
    n_in, n_out = len(rows), len(out_list)
    print(f"{path.name}: {n_in} linhas -> {n_out} únicas (após dedupe)")
    if not dry:
        with path.open("w", encoding=ENCODING, newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in out_list:
                writer.writerow({k: row.get(k, "") for k in fieldnames})
    else:
        print("[dry-run] Não regravou ficheiro.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Consolida CSVs TradingView, deduplica linhas e arquiva originais."
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path(
            "/Users/eduardoribeiro/Library/CloudStorage/GoogleDrive-edunius@gmail.com/"
            "Meu Drive/Trades/Import TradingView"
        ),
        help="Pasta com os CSVs a importar",
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=Path(
            "/Users/eduardoribeiro/Library/CloudStorage/GoogleDrive-edunius@gmail.com/"
            "Meu Drive/Trades/Histórico"
        ),
        help="Pasta para onde mover os CSVs após consolidação",
    )
    parser.add_argument(
        "--output-name",
        default=DEFAULT_OUTPUT,
        help=f"Nome do ficheiro consolidado na pasta de origem (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra o que faria sem escrever nem mover ficheiros",
    )
    parser.add_argument(
        "--round-decimals",
        type=int,
        default=DEFAULT_ROUND_DECIMALS,
        metavar="N",
        help=(
            "Casas decimais ao comparar números na dedupe "
            f"(default: {DEFAULT_ROUND_DECIMALS})"
        ),
    )
    parser.add_argument(
        "--dedupe-in-place",
        type=Path,
        default=None,
        metavar="FILE",
        help=(
            "Só deduplica e regrava este CSV (ex.: consolidado já existente); "
            "ordena por Time (mais recente primeiro). Não move ficheiros."
        ),
    )
    args = parser.parse_args()

    round_decimals = max(0, args.round_decimals)
    if args.dedupe_in_place is not None:
        target = args.dedupe_in_place.expanduser().resolve()
        if not target.is_file():
            print(f"Erro: ficheiro não encontrado: {target}", file=sys.stderr)
            return 1
        return dedupe_in_place(target, args.dry_run, round_decimals)

    source_dir: Path = args.source_dir.expanduser().resolve()
    archive_dir: Path = args.archive_dir.expanduser().resolve()
    output_name = args.output_name
    dry = args.dry_run

    if not source_dir.is_dir():
        print(f"Erro: pasta de origem não existe: {source_dir}", file=sys.stderr)
        return 1

    all_csv = sorted(source_dir.glob("*.csv"))
    input_files = list(all_csv)
    if not input_files:
        print(f"Nenhum CSV em {source_dir}.")
        return 0

    fieldnames: list[str] = []
    unique_rows: dict[tuple[str, ...], dict[str, str]] = {}

    for path in input_files:
        cols, rows = read_rows(path)
        if not cols:
            print(f"Aviso: sem cabeçalho ou vazio: {path.name}", file=sys.stderr)
            continue
        fieldnames = merge_fieldnames(fieldnames, cols)
        for row in rows:
            # Garante chaves para todas as colunas conhecidas
            full = {k: row.get(k, "") for k in fieldnames}
            key = row_key(fieldnames, full, round_decimals)
            if key not in unique_rows:
                unique_rows[key] = full

    if not fieldnames:
        print("Erro: não foi possível determinar colunas a partir dos CSVs.", file=sys.stderr)
        return 1

    out_path = source_dir / output_name
    n_unique = len(unique_rows)

    print(f"Ficheiros de entrada: {len(input_files)}")
    print(f"Linhas únicas (após dedupe): {n_unique}")
    print(f"Consolidado: {out_path}")

    if not dry:
        archive_dir.mkdir(parents=True, exist_ok=True)
        out_list = list(unique_rows.values())
        out_list.sort(key=_parse_time_sort, reverse=True)
        with out_path.open("w", encoding=ENCODING, newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in out_list:
                writer.writerow({k: row.get(k, "") for k in fieldnames})

        for path in input_files:
            if path.name == output_name:
                # O consolidado é lido como entrada e regravado aqui; não vai para o histórico.
                continue
            dest = archive_dir / path.name
            if dest.exists():
                stem, suf = dest.stem, dest.suffix
                n = 1
                while dest.exists():
                    dest = archive_dir / f"{stem}_{n}{suf}"
                    n += 1
            shutil.move(str(path), str(dest))
            print(f"Movido: {path.name} -> {dest}")
    else:
        print("[dry-run] Não gravou consolidado nem moveu ficheiros.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# openpyxl Hands Off

Do not use openpyxl to save or write to an existing `.xlsx` file that carries custom formatting. Read-only use (`load_workbook(..., read_only=True)`, or opening to inspect formulas and values) is fine. Creating a brand-new `.xlsx` from scratch is fine. Anything that overwrites an existing formatted workbook is forbidden.

## Why

openpyxl rewrites the entire XML inside a workbook on save. That rewrite scrambles style definitions, conditional formatting, table styles, banded rows, and theme-based colors, and after the save, later formatting changes in the spreadsheet application cascade-reset adjacent cells. The damage is silent at write time and surfaces only when someone opens the file, which is usually after the original is gone. A guard at the shell boundary is cheaper than a restore from backup.

## Application

- When asked to modify a formatted spreadsheet, deliver the exact values, formulas, and target cells as text instructions for the operator to paste, or use a tool that preserves formatting (a COM bridge, a templated rebuild, or a surgical zip/XML patch on the target cells followed by a headless recalculation).
- When writing a brand-new sheet, openpyxl is acceptable; state explicitly that no existing formatting is being touched.
- The guard hook (hard-block rung, see [hook-design](hook-design.md)) denies the pattern of `openpyxl` plus a `.save()` call against an existing file at the shell tool boundary, both when the code is inline in the command and when the command references a `.py` script that contains it. Do not try to route around the guard; the right move is to switch tools.

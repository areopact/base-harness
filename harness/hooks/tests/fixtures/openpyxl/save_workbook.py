"""Regression fixture: a script that writes an existing workbook with openpyxl.

Never executed by the tests; the guard reads it as evidence when a shell
command references it.
"""
import openpyxl

wb = openpyxl.load_workbook("harness/hooks/tests/fixtures/openpyxl/formatted-workbook.xlsx")
wb["Sheet1"]["A1"] = "edited"
wb.save("harness/hooks/tests/fixtures/openpyxl/formatted-workbook.xlsx")

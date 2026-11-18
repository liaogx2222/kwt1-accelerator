# -*- coding: utf-8 -*-
"""用本机 Word 更新目录域、重排并导出 PDF（替代 export_word.ps1）。

PowerShell 5.1 以 ANSI 读取无 BOM 的 .ps1，中文文件名会乱码，
因此改为 Python 调用 Word COM。
"""
import os
import win32com.client as win32

NAME = "KWT1_Technical_Report_LN4"
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, NAME + ".docx")
DST = os.path.join(BASE, NAME + ".pdf")

app = win32.gencache.EnsureDispatch("Word.Application")
app.Visible = False
app.DisplayAlerts = 0
doc = app.Documents.Open(SRC, ReadOnly=False)
try:
    doc.Fields.Update()
    for toc in doc.TablesOfContents:
        toc.Update()
    doc.Repaginate()
    pages = doc.ComputeStatistics(2)
    doc.Save()
    doc.SaveAs(DST, FileFormat=17)
finally:
    doc.Close(SaveChanges=0)
    app.Quit()
print("pages:", pages)
print("ok", DST, os.path.getsize(DST))

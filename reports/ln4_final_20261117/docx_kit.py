# -*- coding: utf-8 -*-
"""DOCX 排版工具集：中文技术报告所需的样式、表格、图表与页眉页脚。"""
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import copy

HEI = "黑体"
SONG = "宋体"
KAI = "楷体"
MONO = "Consolas"

ACCENT = RGBColor(0x1F, 0x3B, 0x63)      # 深蓝
GREY = RGBColor(0x59, 0x59, 0x59)
HEAD_FILL = "1F3B63"
SUB_FILL = "DCE6F1"
LIGHT_FILL = "F2F5F9"
WARN_FILL = "FBE9E7"


def _set_run_font(run, ascii_font=SONG, ea_font=SONG, size=None, bold=None, color=None, italic=None):
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic
    if color is not None:
        run.font.color.rgb = color
    run.font.name = ascii_font
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn('w:rFonts'))
    if rf is None:
        rf = OxmlElement('w:rFonts')
        rpr.insert(0, rf)
    rf.set(qn('w:ascii'), ascii_font)
    rf.set(qn('w:hAnsi'), ascii_font)
    rf.set(qn('w:eastAsia'), ea_font)


def shade(cell, hexfill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hexfill)
    tcPr.append(shd)


def cell_margins(table, top=40, bottom=40, left=80, right=80):
    tblPr = table._tbl.tblPr
    mar = OxmlElement('w:tblCellMar')
    for tag, val in (('top', top), ('left', left), ('bottom', bottom), ('right', right)):
        el = OxmlElement('w:' + tag)
        el.set(qn('w:w'), str(val))
        el.set(qn('w:type'), 'dxa')
        mar.append(el)
    tblPr.append(mar)


def set_borders(table, sz=4, color="D9D9D9"):
    tbl = table._tbl
    tblPr = tbl.tblPr
    borders = OxmlElement('w:tblBorders')
    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        el = OxmlElement('w:' + edge)
        el.set(qn('w:val'), 'single')
        el.set(qn('w:sz'), str(sz))
        el.set(qn('w:space'), '0')
        el.set(qn('w:color'), color)
        borders.append(el)
    tblPr.append(borders)


def keep_with_next(par):
    par.paragraph_format.keep_with_next = True


def add_field(par, instr, placeholder="1"):
    fld = OxmlElement('w:fldSimple')
    fld.set(qn('w:instr'), instr)
    r = OxmlElement('w:r')
    t = OxmlElement('w:t')
    t.text = placeholder
    r.append(t)
    fld.append(r)
    par._p.append(fld)


class Report:
    def __init__(self, body_pt=10.5):
        self.doc = Document()
        self.body_pt = body_pt
        self.fig_no = 0
        self.tab_no = 0
        self._setup_page()
        self._setup_styles()

    # ---------- 页面与样式 ----------
    def _setup_page(self):
        s = self.doc.sections[0]
        s.page_width = Cm(21.0)
        s.page_height = Cm(29.7)
        s.top_margin = Cm(2.4)
        s.bottom_margin = Cm(2.2)
        s.left_margin = Cm(2.6)
        s.right_margin = Cm(2.4)
        s.header_distance = Cm(1.3)
        s.footer_distance = Cm(1.2)

    def _setup_styles(self):
        st = self.doc.styles
        n = st['Normal']
        n.font.size = Pt(self.body_pt)
        n.font.name = SONG
        n.element.rPr.rFonts.set(qn('w:eastAsia'), SONG)
        n.paragraph_format.line_spacing = 1.35
        n.paragraph_format.space_before = Pt(0)
        n.paragraph_format.space_after = Pt(3)

        specs = [('Heading 1', 16, HEI, 16, 8), ('Heading 2', 13, HEI, 12, 6), ('Heading 3', 11.5, HEI, 9, 5)]
        for name, size, font, before, after in specs:
            h = st[name]
            h.font.size = Pt(size)
            h.font.name = font
            h.font.bold = True
            h.font.color.rgb = RGBColor(0, 0, 0)
            h.element.rPr.rFonts.set(qn('w:eastAsia'), font)
            h.paragraph_format.space_before = Pt(before)
            h.paragraph_format.space_after = Pt(after)
            h.paragraph_format.line_spacing = 1.15
            h.paragraph_format.keep_with_next = True

    def header_footer(self, header_text):
        sec = self.doc.sections[0]
        hp = sec.header.paragraphs[0]
        hp.text = ""
        hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = hp.add_run(header_text)
        _set_run_font(r, SONG, SONG, 8.5, color=RGBColor(0, 0, 0))
        pPr = hp._p.get_or_add_pPr()
        pbdr = OxmlElement('w:pBdr')
        bottom = OxmlElement('w:bottom')
        bottom.set(qn('w:val'), 'single')
        bottom.set(qn('w:sz'), '4')
        bottom.set(qn('w:space'), '1')
        bottom.set(qn('w:color'), '8EA9C1')
        pbdr.append(bottom)
        pPr.append(pbdr)

        fp = sec.footer.paragraphs[0]
        fp.text = ""
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r1 = fp.add_run("— ")
        _set_run_font(r1, SONG, SONG, 9, color=GREY)
        add_field(fp, 'PAGE', '1')
        r2 = fp.add_run(" —")
        _set_run_font(r2, SONG, SONG, 9, color=GREY)

    # ---------- 段落 ----------
    def p(self, text, indent=True, size=None, bold=False, align=None, space_after=None, color=None):
        par = self.doc.add_paragraph()
        par.paragraph_format.first_line_indent = Cm(0.74) if indent else Cm(0)
        if align == 'center':
            par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif align == 'justify' or align is None:
            par.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        if space_after is not None:
            par.paragraph_format.space_after = Pt(space_after)
        r = par.add_run(text)
        _set_run_font(r, SONG, SONG, size or self.body_pt, bold=bold, color=color)
        return par

    def rich(self, parts, indent=True, size=None, space_after=None):
        """parts: [(text, bold)] 混排，用于突出关键数字。"""
        par = self.doc.add_paragraph()
        par.paragraph_format.first_line_indent = Cm(0.74) if indent else Cm(0)
        par.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        if space_after is not None:
            par.paragraph_format.space_after = Pt(space_after)
        for text, bold in parts:
            r = par.add_run(text)
            _set_run_font(r, SONG, SONG, size or self.body_pt, bold=bold)
        return par

    def h1(self, text, new_page=False):
        par = self.doc.add_paragraph(style='Heading 1')
        if new_page:
            par.paragraph_format.page_break_before = True
        r = par.add_run(text)
        _set_run_font(r, HEI, HEI, 16, bold=True, color=RGBColor(0, 0, 0))
        return par

    def plain_h1(self, text, new_page=False):
        """与 h1 同样式但不进入目录（用于“目录”标题本身）。"""
        par = self.doc.add_paragraph()
        if new_page:
            par.paragraph_format.page_break_before = True
        par.paragraph_format.space_before = Pt(16)
        par.paragraph_format.space_after = Pt(8)
        par.paragraph_format.line_spacing = 1.15
        r = par.add_run(text)
        _set_run_font(r, HEI, HEI, 16, bold=True, color=RGBColor(0, 0, 0))
        return par

    def h2(self, text):
        par = self.doc.add_paragraph(style='Heading 2')
        r = par.add_run(text)
        _set_run_font(r, HEI, HEI, 13, bold=True, color=RGBColor(0, 0, 0))
        return par

    def h3(self, text):
        par = self.doc.add_paragraph(style='Heading 3')
        r = par.add_run(text)
        _set_run_font(r, HEI, HEI, 11.5, bold=True, color=RGBColor(0, 0, 0))
        return par

    def _rule(self, par, color, sz):
        pPr = par._p.get_or_add_pPr()
        pbdr = OxmlElement('w:pBdr')
        bottom = OxmlElement('w:bottom')
        bottom.set(qn('w:val'), 'single')
        bottom.set(qn('w:sz'), str(sz))
        bottom.set(qn('w:space'), '2')
        bottom.set(qn('w:color'), color)
        pbdr.append(bottom)
        pPr.append(pbdr)

    def bullet(self, text, size=None, level=0):
        par = self.doc.add_paragraph()
        par.paragraph_format.left_indent = Cm(0.9 + 0.6 * level)
        par.paragraph_format.first_line_indent = Cm(-0.42)
        par.paragraph_format.space_after = Pt(2)
        par.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        r = par.add_run("▪ " if level == 0 else "· ")
        _set_run_font(r, SONG, SONG, size or self.body_pt, color=ACCENT)
        r2 = par.add_run(text)
        _set_run_font(r2, SONG, SONG, size or self.body_pt)
        return par

    def note(self, text, fill=WARN_FILL, size=9.5):
        """带底色的提示块（单格表格）。"""
        return self.p(text, indent=False, size=size)
        t = self.doc.add_table(rows=1, cols=1)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        cell = t.cell(0, 0)
        cell.text = ""
        shade(cell, fill)
        set_borders(t, 4, "D9B0A8" if fill == WARN_FILL else "B6C4D6")
        par = cell.paragraphs[0]
        par.paragraph_format.space_after = Pt(2)
        par.paragraph_format.line_spacing = 1.2
        r = par.add_run(text)
        _set_run_font(r, SONG, SONG, size)
        self.spacer(4)

    def figure(self, path, width_cm=15.4, cap=None):
        par = self.doc.add_paragraph()
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        par.paragraph_format.space_before = Pt(4)
        par.paragraph_format.space_after = Pt(2)
        par.paragraph_format.keep_with_next = True
        par.add_run().add_picture(path, width=Cm(width_cm))
        if cap:
            self.caption(cap, 'fig')
        return par

    def caption(self, text, kind='tab'):
        if kind == 'tab':
            self.tab_no += 1
            label = "表 %d  %s" % (self.tab_no, text)
        else:
            self.fig_no += 1
            label = "图 %d  %s" % (self.fig_no, text)
        par = self.doc.add_paragraph()
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        par.paragraph_format.space_before = Pt(2)
        par.paragraph_format.space_after = Pt(5 if kind == 'tab' else 8)
        if kind == 'tab':
            par.paragraph_format.keep_with_next = True
        r = par.add_run(label)
        _set_run_font(r, HEI, HEI, 9, bold=False, color=GREY)
        return par

    def spacer(self, pt=6):
        par = self.doc.add_paragraph()
        par.paragraph_format.space_after = Pt(0)
        par.paragraph_format.line_spacing = 1.0
        r = par.add_run("")
        _set_run_font(r, SONG, SONG, max(1, pt))
        return par

    # ---------- 表格 ----------
    def table(self, headers, rows, widths=None, size=9, header_fill=HEAD_FILL,
              zebra=True, aligns=None, bold_rows=(), first_col_bold=False,
              cap=None, mono_cols=(), fill_rows=None, row_fills=None):
        if cap:
            self.caption(cap, 'tab')
        ncol = len(headers)
        if widths:
            tot = sum(widths)
            if tot > 16.0:
                widths = [w * 16.0 / tot for w in widths]
        t = self.doc.add_table(rows=len(rows) + 1, cols=ncol)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        set_borders(t)
        cell_margins(t)
        total = sum(widths) if widths else None
        if widths:
            for i, w in enumerate(widths):
                for row in t.rows:
                    row.cells[i].width = Cm(w)
        # 表头
        for j, h in enumerate(headers):
            c = t.cell(0, j)
            c.text = ""
            shade(c, header_fill)
            par = c.paragraphs[0]
            par.alignment = WD_ALIGN_PARAGRAPH.CENTER
            par.paragraph_format.space_after = Pt(1)
            par.paragraph_format.space_before = Pt(1)
            par.paragraph_format.line_spacing = 1.1
            r = par.add_run(str(h))
            _set_run_font(r, HEI, HEI, size, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
        # 表体
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                c = t.cell(i + 1, j)
                c.text = ""
                from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
                c.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                if row_fills and i in row_fills:
                    shade(c, row_fills[i])
                elif fill_rows and i in fill_rows:
                    shade(c, fill_rows[i])
                elif zebra and i % 2 == 1:
                    shade(c, LIGHT_FILL)
                par = c.paragraphs[0]
                al = (aligns[j] if aligns else ('left' if j == 0 else 'center'))
                par.alignment = {'left': WD_ALIGN_PARAGRAPH.LEFT, 'center': WD_ALIGN_PARAGRAPH.CENTER,
                                 'right': WD_ALIGN_PARAGRAPH.RIGHT}[al]
                par.paragraph_format.space_after = Pt(1)
                par.paragraph_format.space_before = Pt(1)
                par.paragraph_format.line_spacing = 1.08
                r = par.add_run(str(val))
                bold = (i in bold_rows) or (first_col_bold and j == 0)
                _set_run_font(r, MONO if j in mono_cols else SONG, SONG, size, bold=bold)
        # 表头重复
        trPr = t.rows[0]._tr.get_or_add_trPr()
        th = OxmlElement('w:tblHeader')
        th.set(qn('w:val'), 'true')
        trPr.append(th)
        # 行内不断页；行间尽量不拆表
        for ri, row in enumerate(t.rows):
            rp = row._tr.get_or_add_trPr()
            cs = OxmlElement('w:cantSplit')
            cs.set(qn('w:val'), 'true')
            rp.append(cs)
            if ri == 0:
                for c in row.cells:
                    for par in c.paragraphs:
                        par.paragraph_format.keep_with_next = True
        if cap:
            pass
        else:
            self.spacer(4)
        return t

    def bar_table(self, rows, cap=None, width=14.2, unit="", vmax=None, note_col=True):
        """用表格单元格底色画条形图：rows = [(label, value, text)]"""
        vals = [v for _, v, _ in rows]
        mx = vmax or max(vals)
        nrow, ncol = len(rows), 12
        t = self.doc.add_table(rows=nrow, cols=ncol)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        cell_margins(t, 20, 20, 40, 40)
        set_borders(t, 2, "FFFFFF")
        lab_w, num_w = 4.4, 2.4
        bar_w = width - lab_w - num_w
        for r_i, (label, val, txt) in enumerate(rows):
            cells = t.rows[r_i].cells
            cells[0].width = Cm(lab_w)
            p = cells[0].paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.space_after = Pt(1)
            p.paragraph_format.space_before = Pt(1)
            run = p.add_run(label)
            _set_run_font(run, SONG, SONG, 9)
            # 条形区
            filled = int(round(val / mx * (ncol - 3)))
            filled = max(1, min(ncol - 3, filled))
            for j in range(1, ncol - 1):
                c = cells[j]
                c.width = Cm(bar_w / (ncol - 2))
                if j <= filled:
                    shade(c, "4F7CB1" if val < mx * 0.999 else "C0504D")
                else:
                    shade(c, "FFFFFF")
                pp = c.paragraphs[0]
                pp.paragraph_format.space_after = Pt(1)
                pp.paragraph_format.space_before = Pt(1)
                pp.paragraph_format.line_spacing = 1.0
                rr = pp.add_run("")
                _set_run_font(rr, SONG, SONG, 6)
            cells[ncol - 1].width = Cm(num_w)
            p2 = cells[ncol - 1].paragraphs[0]
            p2.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            p2.paragraph_format.space_after = Pt(1)
            p2.paragraph_format.space_before = Pt(1)
            r2 = p2.add_run(txt)
            _set_run_font(r2, MONO if not unit else SONG, SONG, 9, bold=True)
        if cap:
            self.caption(cap, 'fig')
        else:
            self.spacer(4)
        return t

    def kv_block(self, pairs, cap=None, key_w=4.6, val_w=11.4):
        """两列键值表，用于参数清单。"""
        return self.table(["项", "值"], [[k, v] for k, v in pairs], widths=[key_w, val_w], cap=cap)

    def page_break(self):
        par = self.doc.add_paragraph()
        par.add_run().add_break(WD_BREAK.PAGE)

    def toc(self):
        """插入标准 TOC 域；打开文档时由 Word 自动更新（已置 updateFields）。"""
        par = self.doc.add_paragraph()

        def _r():
            e = OxmlElement('w:r')
            return e

        r1 = _r(); fc = OxmlElement('w:fldChar'); fc.set(qn('w:fldCharType'), 'begin'); r1.append(fc)
        r2 = _r(); it = OxmlElement('w:instrText'); it.set(qn('xml:space'), 'preserve')
        it.text = r' TOC \o "1-2" \h \z \u '; r2.append(it)
        r3 = _r(); fc2 = OxmlElement('w:fldChar'); fc2.set(qn('w:fldCharType'), 'separate'); r3.append(fc2)
        r4 = _r(); t = OxmlElement('w:t'); t.text = "目录将在打开文档时自动生成"; r4.append(t)
        r5 = _r(); fc3 = OxmlElement('w:fldChar'); fc3.set(qn('w:fldCharType'), 'end'); r5.append(fc3)
        for r in (r1, r2, r3, r4, r5):
            par._p.append(r)
        return par

    def enable_update_fields(self):
        settings = self.doc.settings.element
        uf = OxmlElement('w:updateFields')
        uf.set(qn('w:val'), 'true')
        settings.append(uf)

    def save(self, path):
        self.doc.save(path)

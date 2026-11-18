# -*- coding: utf-8 -*-
"""汇总生成最新版技术报告 DOCX。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from docx_kit import Report
import part1
import part2
import current
import part4

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "KWT1_Technical_Report_LN4.docx")


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    R = Report(body_pt=10.5)
    R.doc.core_properties.author = "KWT-1"
    R.doc.core_properties.title = "KWT1 Technical Report（LN4 优化版）"
    R.header_footer("KWT1 Technical Report · 整数 Transformer 加速器设计与实测")
    # 封面不显示页眉页脚
    R.doc.sections[0].different_first_page_header_footer = True
    part1.cover(R)
    current.abstract(R)
    part1.toc(R)
    part1.ch1(R)
    part1.ch2(R)
    part1.ch3(R)
    part2.ch4(R)
    current.ch5(R)
    current.ch6(R)
    current.ch7(R)
    current.ch8(R)
    current.ch9(R)
    current.ch10(R)
    current.ch11(R)
    current.ch12(R)
    part4.appendix(R)
    # Keep chapters together naturally without one-paragraph trailing pages.
    for p in R.doc.paragraphs:
        if p.style.name == 'Heading 1' and p.text[:1].isdigit():
            p.paragraph_format.page_break_before = p.text.startswith(('1　', '12　'))
    # The retained Word Title style contains an inherited theme border.
    title_style = R.doc.styles['Title']
    for border in title_style.element.xpath('.//w:pBdr'):
        border.getparent().remove(border)
    title_style.font.color.rgb = __import__('docx').shared.RGBColor(0, 0, 0)
    for color in title_style.element.xpath('.//w:color'):
        for k in list(color.attrib):
            if k.endswith(('themeColor', 'themeShade', 'themeTint')):
                del color.attrib[k]
    R.enable_update_fields()
    R.save(OUT)
    print("saved", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()

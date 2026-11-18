"""Use the packaged render_docx rasterizer after native Word PDF conversion.

Windows has Word but no LibreOffice. Only convert_to_pdf is substituted with
the PDF exported from this exact DOCX; rasterization/naming remain skill code.
"""
from pathlib import Path
import importlib.util
import os
import tempfile
B=Path(__file__).resolve().parent
(B/'qa/temp').mkdir(parents=True,exist_ok=True)
tempfile.tempdir=str(B/'qa/temp')
deps=Path('C:/Users/123/.cache/codex-runtimes/codex-primary-runtime/dependencies')
os.environ['PATH']=str(deps/'native/poppler/Library/bin')+os.pathsep+os.environ['PATH']
skill=Path('C:/Users/123/.codex/plugins/cache/openai-primary-runtime/documents/26.1110.11613/skills/documents/render_docx.py')
spec=importlib.util.spec_from_file_location('render_docx',skill)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
doc=B/'30022_uv_KWT1_作品设计报告_LN4优化版.docx'
pdf=doc.with_suffix('.pdf')
assert pdf.is_file() and pdf.stat().st_mtime >= doc.stat().st_mtime
for old in list((B/'qa/pages').glob('page-*.png'))+list((B/'qa').glob('contact_*.png')):
    assert (B/'qa').resolve() in old.resolve().parents
    old.unlink()
mod.convert_to_pdf=lambda *args,**kwargs:(str(pdf),'Native Word ExportAsFixedFormat; no LibreOffice installed')
pages=mod.rasterize(str(doc),str(B/'qa/pages'),144,True,False)
from PIL import Image,ImageDraw
for start in range(0,len(pages),6):
    sheet=Image.new('RGB',(1200,1800),'#dddddd');dd=ImageDraw.Draw(sheet)
    for i,p in enumerate(pages[start:start+6]):
        tile=Image.open(p);tile.thumbnail((570,550))
        x=(i%2)*600+15;y=(i//2)*600+30
        sheet.paste(tile,(x,y));dd.text((x,y-20),'PAGE '+str(start+i+1),fill='black')
    sheet.save(B/('qa/contact_%02d.png'%(start//6+1)))
print('RENDERED_PAGES',len(pages))

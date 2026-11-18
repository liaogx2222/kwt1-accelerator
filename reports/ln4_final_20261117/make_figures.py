"""Draw the actual System Bus route with PIL; no generated conceptual image."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
B=Path(__file__).resolve().parent
im=Image.new('RGB',(1900,1320),'white');d=ImageDraw.Draw(im)
font='C:/Windows/Fonts/msyh.ttc'
def box(x,y,w,h,title,body):
    d.rectangle((x,y,x+w,y+h),fill='#eef3f9',outline='#526a83',width=3)
    ft=ImageFont.truetype(font,32);fb=ImageFont.truetype(font,27)
    d.text((x+w/2,y+25),title,font=ft,fill='black',anchor='mt')
    for i,line in enumerate(body.splitlines()):
        d.text((x+w/2,y+82+i*44),line,font=fb,fill='#26394a',anchor='mt')
def arrow(x,y,xx,yy):
    import math
    d.line((x,y,xx,yy),fill='#294f75',width=5)
    a=math.atan2(yy-y,xx-x)
    pts=[(xx,yy)]+[(xx-20*math.cos(a+t),yy-20*math.sin(a+t)) for t in (-.5,.5)]
    d.polygon(pts,fill='#294f75')
box(60,45,540,220,'E203 CPU 请求','原内存请求\n固定 ROM 调度')
box(680,45,540,220,'NICE 块搬运请求','CPU 提交并保留所有权\n只访问共享 SRAM 区间')
box(1300,45,540,220,'平台供包 ICB 请求','输入及13个参数包\n真实总线响应后确认')
for x in (330,950,1570):arrow(x,265,x,375)
box(60,375,1780,160,'原 System Bus 入口的三主仲裁','32 bit   公平轮转   请求保持   响应所有权   组合零延迟响应')
arrow(950,535,950,620)
box(60,620,1780,160,'原 e203_subsys_mems 地址译码','原 sysmem 与 SysPer 路径   不增加共享 SRAM 物理端口')
arrow(480,780,480,885);arrow(1420,780,1420,885)
box(60,885,840,300,'512 KiB 共享 SRAM','原 sysmem ICB 单一从口\n64 × 4096×16 宏\n参数与输入读出、结果写回均走原总线\n无测试台直写和独立写回旁路')
box(1000,885,840,300,'加速器与 MMIO 桥','SysPer 0x1100_0000\n8×16 PE   四路精确整数算术\n20 × 4096×16 私有宏\n块数据来自已完成的总线读响应')
d.text((950,1240),'原 System Bus 统一供数  ·  32 bit 接口  ·  参数与最终结果经共享 SRAM 交接',
       font=ImageFont.truetype(font,28),fill='black',anchor='mt')
im.save(B/'fig_soc.png')
print('FIGURE_WRITTEN')

# Terminology in the storage diagram follows the report text: bank.
im=Image.new('RGB',(2000,1000),'white');d=ImageDraw.Draw(im)
ft=ImageFont.truetype(font,35);fb=ImageFont.truetype(font,27)
groups=[(60,'8 个权重 bank',[
    ('Q','0–255'),('K','256–511'),('V','512–767'),('O','768–1023'),
    ('FC1','1024–2047'),('FC2 槽 A','2048–3071'),('FC2 槽 B','3072–4095')]),
    (1080,'8 个激活 bank',[
    ('X / LN1 输出','0'),('Q','448'),('K','896'),('V','1344'),('context','1792'),
    ('O / FC2 输出','2240'),('FC1 隐层 / LN2 输出','448'),('S16 输入','2688–3519')])]
for x,title,items in groups:
    d.text((x+430,30),title,font=ft,fill='black',anchor='mt')
    d.text((x+430,90),'4096×16 单口宏   每个 bank 的地址映射相同',font=fb,fill='#334455',anchor='mt')
    for i,(name,addr) in enumerate(items):
        y=160+80*i
        d.rectangle((x,y,x+860,y+68),fill='#dce6f1' if i%2==0 else '#edf2f7',outline='#a6b7c8',width=2)
        d.text((x+22,y+19),name,font=fb,fill='#193750')
        d.text((x+838,y+19),addr,font=fb,fill='#193750',anchor='rt')
d.text((1000,870),'另有4个系数与查找表bank   ·   20个单口宏共160 KiB',font=ft,fill='black',anchor='mt')
im.save(B/'fig_banks.png')
print('BANK_FIGURE_WRITTEN')

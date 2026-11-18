import io

src = io.open('make_pos.py', encoding='utf-8').read()
src = src.replace(
    '/path/to/project/server_signoff_20261106/keyword-transformer/rtl/integration/smic40/kwt_tech_sram_4096x16.sv',
    'E:/project/ChipCompetition/keyword-transformer/rtl/integration/smic40/kwt_tech_sram_4096x16.sv')
src = src.replace('io.open(p, "w", encoding="utf-8", newline=N).write(o)', 'pass')
src = src.replace('print("patched wrapper,", len(o), "bytes")', 'print(o[o.index("`ifdef KWT_SIM_POSITIONAL") - 200:o.index("endmodule")])')
exec(src)

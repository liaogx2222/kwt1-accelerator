import sys, os, hashlib

p = sys.argv[1] if len(sys.argv) > 1 else '../../tb/tb_soc.sv'
s = open(p).read()

old = """  initial begin
    #2000000;                                   // 2 ms
    $display("RESULT: FAIL (timeout at %0t)", $time);
    $finish;
  end"""

new = """  initial begin
    #20000000;                                  // 20 ms. The wait loop above is
                                                // 2 ms long, so a 2 ms watchdog
                                                // fired 2.6 us before the summary
                                                // and hid every result line.
    $display("RESULT: FAIL (timeout at %0t)", $time);
    $display("  probe: hfclkrst=%b pc_rtvec=0x%08h sysper_rd=%0d sysper_wr=%0d",
             dut.u_e203_subsys_top.hfclkrst, dut.u_e203_subsys_top.pc_rtvec,
             n_rd, n_wr);
    $fflush;
    $finish;
  end"""

if old not in s:
    print('PATTERN NOT FOUND -- file left untouched')
    sys.exit(1)

s = s.replace(old, new, 1)
open(p, 'w', newline='\n').write(s)
b = s.encode()
print('patched %s' % p)
print('bytes %d  md5 %s' % (len(b), hashlib.md5(b).hexdigest()))

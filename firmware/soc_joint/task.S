    lui  t0, 0x11000
    lui  t6, 0xa0000
    addi s1, x0, 0
task_begin:
    lui t4, 0xa0022
    lw   t3, 0x48(t0)
    addi t3, x0, 2
    sw   t3, 0(t0)
    addi t5, s1, 1
    lui s0, 0x100
wmb0:
    lw   t3, 0(t6)
    addi s0, s0, -1
    beq s0, x0, task_failed
    bne  t3, t5, wmb0
    lui  t1, 0xa0001
    lui  t2, 0x1
    addi t2, t2, 48
    addi t3, x0, 256
    jal  ra, send_pkt
    lui s0, 0x100
wcommon:
    lw   t3, 4(t0)
    addi s0, s0, -1
    beq s0, x0, task_failed
    andi s3, t3, 4
    bne s3, x0, task_failed
    andi t3, t3, 8
    beq  t3, x0, wcommon
    lui  t1, 0xa0024
    lui  t2, 0x4
    addi t2, t2, -952
    addi t3, x0, 0
    jal  ra, send_pkt
    lui s0, 0x100
wlyr0:
    lw   t3, 4(t0)
    addi s0, s0, -1
    beq s0, x0, task_failed
    andi s3, t3, 4
    bne s3, x0, task_failed
    andi t3, t3, 32
    beq  t3, x0, wlyr0
    sw   t5, 4(t6)
    lui  t1, 0xa0020
    addi t2, x0, 1584
    jal  ra, send_inp
    lui s0, 0x100
wstart:
    lw t3, 4(t0)
    addi s0, s0, -1
    beq s0, x0, task_failed
    andi s3, t3, 4
    bne s3, x0, task_failed
    andi t3, t3, 256
    beq t3, x0, wstart
    addi t3, x0, 1
    sw   t3, 0(t0)
    addi t5, x0, 1
    lui s0, 0x100
lnext:
    lw   t3, 4(t0)
    addi s0, s0, -1
    beq s0, x0, task_failed
    andi s3, t3, 4
    bne s3, x0, task_failed
    andi t3, t3, 64
    beq  t3, x0, lnext
    addi s2, s1, 1
    add s2, s2, t5
    lui s0, 0x100
wmb:
    lw   t3, 0(t6)
    addi s0, s0, -1
    beq s0, x0, task_failed
    bne  t3, s2, wmb
    lui  t1, 0xa0024
    lui  t2, 0x4
    addi t2, t2, -952
    addi t3, t5, 0
    jal  ra, send_pkt
    lui s0, 0x100
wly:
    lw   t3, 4(t0)
    addi s0, s0, -1
    beq s0, x0, task_failed
    andi s3, t3, 4
    bne s3, x0, task_failed
    andi t3, t3, 32
    beq  t3, x0, wly
    sw   s2, 4(t6)
    addi t5, t5, 1
    addi t3, x0, 12
    bne  t5, t3, lnext
    addi t5, x0, 1584
    lui s0, 0x100
drain:
    lw   t3, 4(t0)
    addi s0, s0, -1
    beq s0, x0, task_failed
    andi s3, t3, 4
    bne s3, x0, task_failed
    srli t3, t3, 12
    andi t3, t3, 1
    beq  t3, x0, drain
    lw   t3, 24(t0)
    sw   t3, 0(t4)
    addi t4, t4, 4
    addi t5, t5, -1
    bne  t5, x0, drain
    lui s0, 0x100
wdone:
    lw   t3, 4(t0)
    addi s0, s0, -1
    beq s0, x0, task_failed
    andi s3, t3, 4
    bne s3, x0, task_failed
    andi t3, t3, 2
    beq  t3, x0, wdone
    addi t3, x0, 0x5A5
    sw   t3, 8(t6)
    addi s1, s1, 16
    jal x0, task_begin
send_pkt:
    sw   t3, 8(t0)
    addi t2, t2, -1
pkt_loop:
    lw   t3, 0(t1)
    sw   t3, 16(t0)
    addi t1, t1, 4
    addi t2, t2, -1
    bne  t2, x0, pkt_loop
    addi t3, x0, 1
    sw   t3, 12(t0)
    lw   t3, 0(t1)
    sw   t3, 16(t0)
    addi t1, t1, 4
    jalr x0, 0(ra)
send_inp:
    addi t2, t2, -1
inp_loop:
    lw   t3, 0(t1)
    sw   t3, 20(t0)
    addi t1, t1, 4
    addi t2, t2, -1
    bne  t2, x0, inp_loop
    addi t3, x0, 1
    sw   t3, 12(t0)
    lw   t3, 0(t1)
    sw   t3, 20(t0)
    addi t1, t1, 4
    jalr x0, 0(ra)
task_failed:
    addi t3, x0, 2
    sw t3, 0(t0)
    lui t3, 0xbad00
    sw t3, 8(t6)
failed_spin:
    jal x0, failed_spin

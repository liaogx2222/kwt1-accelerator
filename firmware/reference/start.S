.section .text.start,"ax",@progbits
.global _start
_start:
 .option push
 .option norelax
 la gp,__global_pointer$
 .option pop
 la sp,__stack_top
 la t0,trap_entry
 csrw mtvec,t0
 la t0,__bss_start
 la t1,__bss_end
1: bgeu t0,t1,2f
 sw zero,0(t0)
 addi t0,t0,4
 j 1b
2: call main
3: j 3b
.align 4
trap_entry:
 csrr a0,mcause
 csrr a1,mepc
 li t0,0x10010000
 sw a0,68(t0)
 sw a1,72(t0)
4: j 4b

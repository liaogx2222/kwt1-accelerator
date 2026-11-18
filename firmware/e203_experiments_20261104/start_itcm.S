.section .text.start,"ax",@progbits
.global _start
_start:
 .option push
 .option norelax
 la gp,__global_pointer$
 .option pop
 la sp,__stack_top
 la t0,boot_trap
 csrw mtvec,t0
 la t0,__itcm_load_start
 la t1,__itcm_start
 la t2,__itcm_end
1: bgeu t1,t2,2f
 lw t3,0(t0)
.global __itcm_copy_store
__itcm_copy_store:
 sw t3,0(t1)
 addi t0,t0,4
 addi t1,t1,4
 j 1b
2: .option push
 .option arch,+zifencei
 fence.i
 .option pop
 la t0,trap_entry
 csrw mtvec,t0
 la t0,__bss_start
 la t1,__bss_end
3: bgeu t0,t1,4f
 sw zero,0(t0)
 addi t0,t0,4
 j 3b
4: call main
5: j 5b
boot_trap:
 csrr a0,mcause
 li t0,0x10010000
 sw a0,68(t0)
6: j 6b
.section .text,"ax",@progbits
.align 4
trap_entry:
 csrr a0,mcause
 csrr a1,mepc
 li t0,0x10010000
 sw a0,68(t0)
 sw a1,72(t0)
7: j 7b

ENTRY(_start)
MEMORY {
 RAM (rwx) : ORIGIN = 0xa0000000, LENGTH = 512K
 ITCM (rwx) : ORIGIN = 0x80000000, LENGTH = 64K
}
SECTIONS {
 .boot ORIGIN(RAM) : { KEEP(*(.text.start)) } >RAM
 .text ORIGIN(ITCM) : AT(ORIGIN(RAM)+0x1000) {
  *(.text*) *(.rodata*) *(.srodata*) . = ALIGN(4);
 } >ITCM
 __itcm_load_start = LOADADDR(.text);
 __itcm_start = ADDR(.text);
 __itcm_end = ADDR(.text)+SIZEOF(.text);
 .data ORIGIN(RAM)+0x2000 : { __global_pointer$ = .+0x800; *(.data*) *(.sdata*) } >RAM
 .bss (NOLOAD) : ALIGN(16) { __bss_start = .; *(.bss*) *(.sbss*) *(COMMON) . = ALIGN(4); __bss_end = .; } >RAM
 __image_end = .;
 __input = ORIGIN(RAM)+0x20000;
 __output = ORIGIN(RAM)+0x22000;
 __packet = ORIGIN(RAM)+0x24000;
 __stack_bottom = ORIGIN(RAM)+0x7c000;
 __stack_top = ORIGIN(RAM)+LENGTH(RAM);
 ASSERT(SIZEOF(.boot)<=0x1000,"bootstrap overlaps ITCM source image")
 ASSERT(__itcm_load_start+SIZEOF(.text)<=ORIGIN(RAM)+0x2000,"ITCM image overlaps small data")
 ASSERT(SIZEOF(.text)<=LENGTH(ITCM),"ITCM overflow")
 ASSERT(__image_end<=__input,"shared image/input overlap")
 ASSERT(__packet+61728<=__stack_bottom,"packet/stack overlap")
}

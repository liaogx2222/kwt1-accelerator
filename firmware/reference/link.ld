ENTRY(_start)
MEMORY { RAM (rwx) : ORIGIN = 0xa0000000, LENGTH = 512K }
SECTIONS {
 . = ORIGIN(RAM);
 .text : { KEEP(*(.text.start)) *(.text*) } >RAM
 .rodata : { *(.rodata*) *(.srodata*) } >RAM
 .data ALIGN(8192) : { __global_pointer$ = .+0x800; *(.data*) *(.sdata*) } >RAM
 .bss (NOLOAD) : ALIGN(16) { __bss_start = .; *(.bss*) *(.sbss*) *(COMMON) . = ALIGN(4); __bss_end = .; } >RAM
 __image_end = .;
 __input = ORIGIN(RAM)+0x20000;
 __output = ORIGIN(RAM)+0x22000;
 __packet = ORIGIN(RAM)+0x24000;
 __stack_bottom = ORIGIN(RAM)+0x7c000;
 __stack_top = ORIGIN(RAM)+LENGTH(RAM);
 ASSERT(__image_end <= __input, "firmware overlaps input")
 ASSERT(__packet+61728 <= __stack_bottom, "packet overlaps stack")
}

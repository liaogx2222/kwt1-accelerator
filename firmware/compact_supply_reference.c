#include <stdint.h>

static volatile uint32_t *const mailbox = (volatile uint32_t *)0x10010000u;
extern uint8_t __packet[];

static uint32_t consume(unsigned frame, uint32_t epoch) {
    uint32_t result;
    uint32_t descriptor = (frame == 0 ? 1u << 20 : (frame - 1) << 16) | epoch;
    __asm__ volatile (".insn r 0x7b, 7, 0x29, %0, %1, %2"
                      : "=r"(result) : "r"(__packet), "r"(descriptor) : "memory");
    return result;
}

int main(void) {
    uint32_t result = 0;
    for (unsigned frame = 0; frame < 13; ++frame) {
        mailbox[2] = frame;
        while (!mailbox[3]) {}
        result = consume(frame, mailbox[4]);
        mailbox[5] = result;
        if (result) break;
    }
    mailbox[1] = result;
    for (;;) {}
}

#include "Vkwt_input16_icb_top.h"
#include "verilated.h"

#include <cstdint>
#include <cstdio>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
Vkwt_input16_icb_top dut;
uint64_t ticks = 0;
std::string root;

void require(bool ok, const char* message) {
    if (!ok) throw std::runtime_error(message);
}

void tick() {
    dut.clk = 0;
    dut.eval();
    dut.clk = 1;
    dut.eval();
    ++ticks;
    if (ticks % 250000 == 0) {
        std::printf("PROGRESS ticks=%llu\n", static_cast<unsigned long long>(ticks));
        std::fflush(stdout);
    }
}

uint32_t transact(uint32_t offset, bool read, uint32_t data = 0, unsigned hold = 0) {
    dut.pa = 0x10000000 | offset;
    dut.pread = read;
    dut.pw = data;
    dut.pmask = 15;
    dut.pv = 1;
    dut.prr = 0;
    unsigned wait = 0;
    while (!dut.pr) {
        tick();
        require(++wait < 128, "ICB request timeout");
    }
    tick();
    dut.pv = 0;
    while (!dut.prv) {
        tick();
        require(++wait < 128, "ICB response timeout");
    }
    const auto value = dut.prd;
    const auto status = dut.bus_rc;
    for (unsigned cycle = 0; cycle < hold; ++cycle) {
        tick();
        require(dut.prv && dut.prd == value && dut.bus_rc == status, "held response changed");
    }
    dut.prr = 1;
    tick();
    dut.prr = 0;
    require(!dut.prv && status == 0, "ICB transaction failed");
    return value;
}

std::vector<uint32_t> words(const std::string& filename) {
    std::ifstream stream(root + '/' + filename);
    require(static_cast<bool>(stream), "missing hex file");
    std::vector<uint32_t> result;
    for (uint32_t word; stream >> std::hex >> word;) result.push_back(word);
    return result;
}

void reset() {
    dut.rst_n = dut.pv = dut.prr = dut.accel_abort = dut.drop_response = 0;
    for (unsigned i = 0; i < 4; ++i) tick();
    dut.rst_n = 1;
    for (unsigned i = 0; i < 4; ++i) tick();
}

void clean() {
    require((transact(4, true) & 0x1ff) == 0, "task state survived cancellation/reset");
    require(!dut.irq && transact(72, true) == 0x4b575432, "S16 device not ready");
}

void packet(int layer) {
    char filename[40];
    if (layer < 0) std::snprintf(filename, sizeof(filename), "common.bin.hex");
    else std::snprintf(filename, sizeof(filename), "layer_%02d.bin.hex", layer);
    auto payload = words(filename);
    require(payload.size() == (layer < 0 ? 4144 : 15432), "incorrect packet length");
    transact(8, false, layer < 0 ? 256 : static_cast<uint32_t>(layer));
    for (size_t i = 0; i < payload.size(); ++i) {
        if (i + 1 == payload.size()) transact(12, false, 1);
        transact(16, false, payload[i]);
    }
    unsigned wait = 0;
    uint32_t status;
    const uint32_t required = layer < 0 ? 8 : layer == 0 ? 32 : 0;
    do {
        status = transact(4, true);
        require(!(status & 4) && ++wait < 128, "packet CRC or completion error");
    } while ((status & required) != required);
}

void start(unsigned sample) {
    char filename[40];
    std::snprintf(filename, sizeof(filename), "input_%03u.hex", sample);
    auto input = words(filename);
    require(input.size() == 3168, "incorrect S16 input length");
    packet(-1);
    packet(0);
    for (size_t i = 0; i < input.size(); ++i) {
        if (i + 1 == input.size()) transact(12, false, 1);
        transact(20, false, input[i]);
    }
    unsigned wait = 0;
    while (!(transact(4, true) & 256)) require(++wait < 128, "input not committed");
    transact(0, false, 1);
}

void await_inflight_ln() {
    const auto deadline = ticks + 1000000;
    while (((transact(28, true) >> 8) & 255) != 51)
        require(ticks < deadline, "no LN in-flight state");
    require((transact(4, true) & 1) && !dut.irq, "LN probe outside a running task");
}

void cold(unsigned sample) {
    const auto start_tick = ticks;
    const auto words_before = dut.parameter_words;
    start(sample);
    unsigned layer = 1;
    const auto deadline = ticks + 12000000;
    while (true) {
        const auto status = transact(4, true);
        require(!(status & 4) && ticks < deadline, "task error or timeout");
        if (status & 4096) break;
        if (status & 64) {
            require(layer < 12 && ((status >> 16) & 15) == layer, "wrong parameter layer");
            packet(layer++);
        }
    }
    require(layer == 12 && dut.parameter_words - words_before == 189328, "wrong task packet count");
    char filename[40];
    std::snprintf(filename, sizeof(filename), "expected_%03u.hex", sample);
    const auto expected = words(filename);
    require(expected.size() == 1584, "incorrect golden length");
    std::snprintf(filename, sizeof(filename), "mapped_observed_%03u.hex", sample);
    std::ofstream observed(root + '/' + filename);
    for (size_t i = 0; i < expected.size(); ++i) {
        const auto value = transact(24, true, 0, i == 0 || i + 1 == expected.size() ? 9 : 0);
        require(value == expected[i], "output differs from integer golden");
        char line[12];
        std::snprintf(line, sizeof(line), "%08x\n", value);
        observed << line;
    }
    require((transact(4, true) & 2) && dut.irq, "completion IRQ missing");
    std::printf("COLD PASS sample=%u ticks=%llu codes=6336\n", sample,
                static_cast<unsigned long long>(ticks - start_tick));
    std::fflush(stdout);
}
}  // namespace

int main(int argc, char** argv) {
    try {
        require(argc == 2, "usage: simulation fixtures-directory");
        Verilated::commandArgs(argc, argv);
        root = argv[1];
        reset();
        clean();
        cold(0);
        transact(0, false, 2);
        clean();
        start(0);
        await_inflight_ln();
        transact(0, false, 2);
        clean();
        std::puts("INFLIGHT CANCEL PASS");
        start(0);
        await_inflight_ln();
        reset();
        clean();
        std::puts("INFLIGHT RESET PASS");
        cold(1);
        std::puts("PASS cold=2 cancelled=1 reset=1 codes=12672");
        dut.final();
    } catch (const std::exception& error) {
        std::fprintf(stderr, "FAIL at tick %llu: %s\n", static_cast<unsigned long long>(ticks), error.what());
        return 1;
    }
}

`timescale 1ns/1ps
 /*                                                                      
 Copyright 2018-2020 Nuclei System Technology, Inc.                
                                                                         
 Licensed under the Apache License, Version 2.0 (the "License");         
 you may not use this file except in compliance with the License.        
 You may obtain a copy of the License at                                 
                                                                         
     http://www.apache.org/licenses/LICENSE-2.0                          
                                                                         
  Unless required by applicable law or agreed to in writing, software    
 distributed under the License is distributed on an "AS IS" BASIS,       
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and     
 limitations under the License.                                          
 */                                                                      
                                                                         
                                                                         
                                                                         
// =============================================================================
// soc_top -- KWT-1 SoC integration top
// -----------------------------------------------------------------------------
// Structure (bottom-up):
//
//   e203_subsys_top  ........ CPU + ITCM/DTCM/CLINT/PLIC/FIO/PPI + APB perips
//        |  sysper_icb_*   (the 12th and last ICB port of the perips fanout)
//        v
//   icb2kwt ................ ICB slave -> 32-bit req/resp (BASE 0x1100_0000)
//        v
//   kwt1_mmio .............. register file + kwt1_accel wrapper, irq = done|error
//
// Address map (32-bit, as seen by the CPU)
//   0x0000_0000  Boot ROM (sirv_mrom, 8 KiB)      -- mode pins select it
//   0x0200_0000  CLINT
//   0x0800_0000  ITCM   (64 KiB, e203_defines.v E203_ITCM_RAM_DP)
//   0x0C00_0000  PLIC
//   0x1000_0000  PPI  (machine timer / software intf)
//   0x1100_0000  KWT-1 accelerator window  <-- this is the only port we add
//   0x9000_0000  DTCM   (64 KiB)
//   0xF000_0000  FIO  (UART0 @0x100, SPI, I2C, GPIO, ...)
//   0xa000_0000  system shared SRAM (kwt_shmem, 512 KiB, platform block)
//
// Clocking
//   hfextclk is the only clock in this block. e203_subsys_top generates hfclk
//   internally (e203_subsys_hclkgen) and is NOT brought out, so the three
//   add-on blocks (icb2kwt / kwt1_mmio / accel) are clocked by hfextclk
//   directly. At 150 MHz with the core's clock-gating idle path unused this is
//   functionally identical to hfclk; it is recorded as a known deviation
//   (pre-layout, no CTS) rather than hidden. If the core ever asserts
//   core_cgstop while an accelerator access is in flight, the slave would keep
//   advancing -- that cannot happen because the CPU only reaches 0x1100_0000
//   after the ICB command has been accepted by the core's own hfclk logic.
//
// Reset
//   io_pads_aon_erst_n_i_ival is the asynchronous, active-low SoC reset. The
//   add-on blocks get a 2-flop synchronised version (async assert / sync
//   deassert) so that their release is aligned to hfextclk.
// =============================================================================
module soc_top(

    // This clock should comes from the crystal pad generated high speed clock (16MHz)
  input  hfextclk,
  output hfxoscen,// The signal to enable the crystal pad generated clock

  // This clock should comes from the crystal pad generated low speed clock (32.768KHz)
  input  lfextclk,
  output lfxoscen,// The signal to enable the crystal pad generated clock


  // The JTAG TCK is input, need to be pull-up
  input   io_pads_jtag_TCK_i_ival,

  // The JTAG TMS is input, need to be pull-up
  input   io_pads_jtag_TMS_i_ival,

  // The JTAG TDI is input, need to be pull-up
  input   io_pads_jtag_TDI_i_ival,

  // The JTAG TDO is output have enable
  output  io_pads_jtag_TDO_o_oval,
  output  io_pads_jtag_TDO_o_oe,

  // The GPIO are all bidir pad have enables
  input  [32-1:0] io_pads_gpioA_i_ival,
  output [32-1:0] io_pads_gpioA_o_oval,
  output [32-1:0] io_pads_gpioA_o_oe,

  input  [32-1:0] io_pads_gpioB_i_ival,
  output [32-1:0] io_pads_gpioB_o_oval,
  output [32-1:0] io_pads_gpioB_o_oe,

  //QSPI0 SCK and CS is output without enable
  output  io_pads_qspi0_sck_o_oval,
  output  io_pads_qspi0_cs_0_o_oval,

  //QSPI0 DQ is bidir I/O with enable, and need pull-up enable
  input   io_pads_qspi0_dq_0_i_ival,
  output  io_pads_qspi0_dq_0_o_oval,
  output  io_pads_qspi0_dq_0_o_oe,
  input   io_pads_qspi0_dq_1_i_ival,
  output  io_pads_qspi0_dq_1_o_oval,
  output  io_pads_qspi0_dq_1_o_oe,
  input   io_pads_qspi0_dq_2_i_ival,
  output  io_pads_qspi0_dq_2_o_oval,
  output  io_pads_qspi0_dq_2_o_oe,
  input   io_pads_qspi0_dq_3_i_ival,
  output  io_pads_qspi0_dq_3_o_oval,
  output  io_pads_qspi0_dq_3_o_oe,
  
  // Erst is input need to be pull-up by default
  input   io_pads_aon_erst_n_i_ival,

  // dbgmode are inputs need to be pull-up by default
  input  io_pads_dbgmode0_n_i_ival,
  input  io_pads_dbgmode1_n_i_ival,
  input  io_pads_dbgmode2_n_i_ival,

  // BootRom is input need to be pull-up by default
  input  io_pads_bootrom_n_i_ival,


  // dwakeup is input need to be pull-up by default
  input  io_pads_aon_pmu_dwakeup_n_i_ival,

      // PMU output is just output without enable
  output io_pads_aon_pmu_padrst_o_oval,
  output io_pads_aon_pmu_vddpaden_o_oval ,

  // KWT-1 accelerator interrupt (done | error). Not wired into the PLIC yet:
  // bringing it in would require editing e203_subsys_perips.v, which is
  // vendor RTL. Exposed at the top so a SoC-level TB can poll it.
  output wire accel_irq,

  // ---- platform parameter loader for the 512 KiB shared SRAM -----------
  // Driven by the organiser's parameter-loading simulation environment:
  // one 32-bit word per cycle, word address inside the 512 KiB window
  // (byte address = 0xa000_0000 + 4*shmem_host_addr).
  input  wire        shmem_host_en,
  input  wire [16:0] shmem_host_addr,
  input  wire [31:0] shmem_host_wdata
);


 
 // ---- sysper ICB: the only bus port this SoC actually answers ---------
 wire        sysper_icb_cmd_valid;
 wire        sysper_icb_cmd_ready;
 wire [31:0] sysper_icb_cmd_addr;
 wire        sysper_icb_cmd_read;
 wire [31:0] sysper_icb_cmd_wdata;
 wire [3:0]  sysper_icb_cmd_wmask;

 wire        sysper_icb_rsp_valid;
 wire        sysper_icb_rsp_ready;
 wire        sysper_icb_rsp_err;
 wire [31:0] sysper_icb_rsp_rdata;

 // ---- KWT accelerator request/response bus (icb2kwt -> kwt1_mmio) -----
 wire        kwt_req_valid;
 wire        kwt_req_ready;
 wire        kwt_req_write;
 wire [31:0] kwt_req_addr;
 wire [31:0] kwt_req_wdata;
 wire [3:0]  kwt_req_wstrb;

 wire        kwt_resp_valid;
 wire        kwt_resp_ready;
 wire [31:0] kwt_resp_rdata;
 wire        kwt_resp_error;

 // ---- reset synchroniser for the add-on blocks ------------------------
 // async assert, 2-flop sync deassert. e203_subsys_top has its own internal
 // reset synchroniser; this one only serves icb2kwt / kwt1_mmio.
 reg  [1:0]  rst_sync;
 always @(posedge hfextclk or negedge io_pads_aon_erst_n_i_ival) begin
   if (!io_pads_aon_erst_n_i_ival) rst_sync <= 2'b00;
   else                            rst_sync <= {rst_sync[0], 1'b1};
 end
 wire kwt_rst_n = rst_sync[1];

 wire sysfio_icb_cmd_valid;
 wire sysfio_icb_cmd_ready;

 wire sysmem_icb_cmd_valid;
 wire sysmem_icb_cmd_ready;
 wire        sysmem_icb_cmd_read;
 wire [31:0] sysmem_icb_cmd_addr;
 wire [31:0] sysmem_icb_cmd_wdata;
 wire [3:0]  sysmem_icb_cmd_wmask;
 wire        sysmem_icb_rsp_valid;
 wire        sysmem_icb_rsp_ready;
 wire        sysmem_icb_rsp_err;
 wire [31:0] sysmem_icb_rsp_rdata;

 e203_subsys_top u_e203_subsys_top(
    .core_mhartid      (1'b0),
  



  `ifdef E203_HAS_ITCM_EXTITF //{
    .ext2itcm_icb_cmd_valid  (1'b0),
    .ext2itcm_icb_cmd_ready  (),
    .ext2itcm_icb_cmd_addr   (`E203_ITCM_ADDR_WIDTH'b0 ),
    .ext2itcm_icb_cmd_read   (1'b0 ),
    .ext2itcm_icb_cmd_wdata  (32'b0),
    .ext2itcm_icb_cmd_wmask  (4'b0),
    
    .ext2itcm_icb_rsp_valid  (),
    .ext2itcm_icb_rsp_ready  (1'b0),
    .ext2itcm_icb_rsp_err    (),
    .ext2itcm_icb_rsp_rdata  (),
  `endif//}

  `ifdef E203_HAS_DTCM_EXTITF //{
    .ext2dtcm_icb_cmd_valid  (1'b0),
    .ext2dtcm_icb_cmd_ready  (),
    .ext2dtcm_icb_cmd_addr   (`E203_DTCM_ADDR_WIDTH'b0 ),
    .ext2dtcm_icb_cmd_read   (1'b0 ),
    .ext2dtcm_icb_cmd_wdata  (32'b0),
    .ext2dtcm_icb_cmd_wmask  (4'b0),
    
    .ext2dtcm_icb_rsp_valid  (),
    .ext2dtcm_icb_rsp_ready  (1'b0),
    .ext2dtcm_icb_rsp_err    (),
    .ext2dtcm_icb_rsp_rdata  (),
  `endif//}

  .sysper_icb_cmd_valid (sysper_icb_cmd_valid),
  .sysper_icb_cmd_ready (sysper_icb_cmd_ready),
  .sysper_icb_cmd_read  (sysper_icb_cmd_read ),
  .sysper_icb_cmd_addr  (sysper_icb_cmd_addr ),
  .sysper_icb_cmd_wdata (sysper_icb_cmd_wdata),
  .sysper_icb_cmd_wmask (sysper_icb_cmd_wmask),

  .sysper_icb_rsp_valid (sysper_icb_rsp_valid),
  .sysper_icb_rsp_ready (sysper_icb_rsp_ready),
  .sysper_icb_rsp_err   (sysper_icb_rsp_err  ),
  .sysper_icb_rsp_rdata (sysper_icb_rsp_rdata),


  .sysfio_icb_cmd_valid(sysfio_icb_cmd_valid),
  .sysfio_icb_cmd_ready(sysfio_icb_cmd_ready),
  .sysfio_icb_cmd_read (), 
  .sysfio_icb_cmd_addr (), 
  .sysfio_icb_cmd_wdata(), 
  .sysfio_icb_cmd_wmask(), 
   
  .sysfio_icb_rsp_valid(sysfio_icb_cmd_valid),
  .sysfio_icb_rsp_ready(sysfio_icb_cmd_ready),
  .sysfio_icb_rsp_err  (1'b0  ),
  .sysfio_icb_rsp_rdata(32'b0),

  .sysmem_icb_cmd_valid(sysmem_icb_cmd_valid),
  .sysmem_icb_cmd_ready(sysmem_icb_cmd_ready),
    .sysmem_icb_cmd_read  (sysmem_icb_cmd_read ),
  .sysmem_icb_cmd_addr  (sysmem_icb_cmd_addr ),
  .sysmem_icb_cmd_wdata (sysmem_icb_cmd_wdata),
  .sysmem_icb_cmd_wmask (sysmem_icb_cmd_wmask),

  .sysmem_icb_rsp_valid (sysmem_icb_rsp_valid),
  .sysmem_icb_rsp_ready (sysmem_icb_rsp_ready),
  .sysmem_icb_rsp_err   (sysmem_icb_rsp_err  ),
  .sysmem_icb_rsp_rdata (sysmem_icb_rsp_rdata),

  .io_pads_jtag_TCK_i_ival    (io_pads_jtag_TCK_i_ival    ),
  .io_pads_jtag_TCK_o_oval    (),
  .io_pads_jtag_TCK_o_oe      (),
  .io_pads_jtag_TCK_o_ie      (),
  .io_pads_jtag_TCK_o_pue     (),
  .io_pads_jtag_TCK_o_ds      (),

  .io_pads_jtag_TMS_i_ival    (io_pads_jtag_TMS_i_ival    ),
  .io_pads_jtag_TMS_o_oval    (),
  .io_pads_jtag_TMS_o_oe      (),
  .io_pads_jtag_TMS_o_ie      (),
  .io_pads_jtag_TMS_o_pue     (),
  .io_pads_jtag_TMS_o_ds      (),

  .io_pads_jtag_TDI_i_ival    (io_pads_jtag_TDI_i_ival    ),
  .io_pads_jtag_TDI_o_oval    (),
  .io_pads_jtag_TDI_o_oe      (),
  .io_pads_jtag_TDI_o_ie      (),
  .io_pads_jtag_TDI_o_pue     (),
  .io_pads_jtag_TDI_o_ds      (),

  .io_pads_jtag_TDO_i_ival    (1'b1    ),
  .io_pads_jtag_TDO_o_oval    (io_pads_jtag_TDO_o_oval    ),
  .io_pads_jtag_TDO_o_oe      (io_pads_jtag_TDO_o_oe      ),
  .io_pads_jtag_TDO_o_ie      (),
  .io_pads_jtag_TDO_o_pue     (),
  .io_pads_jtag_TDO_o_ds      (),

  .io_pads_jtag_TRST_n_i_ival (1'b1 ),
  .io_pads_jtag_TRST_n_o_oval (),
  .io_pads_jtag_TRST_n_o_oe   (),
  .io_pads_jtag_TRST_n_o_ie   (),
  .io_pads_jtag_TRST_n_o_pue  (),
  .io_pads_jtag_TRST_n_o_ds   (),

  .test_mode(1'b0),
  .test_iso_override(1'b0),

  .io_pads_gpioA_i_ival       (io_pads_gpioA_i_ival),
  .io_pads_gpioA_o_oval       (io_pads_gpioA_o_oval),
  .io_pads_gpioA_o_oe         (io_pads_gpioA_o_oe), 

  .io_pads_gpioB_i_ival       (io_pads_gpioB_i_ival),
  .io_pads_gpioB_o_oval       (io_pads_gpioB_o_oval),
  .io_pads_gpioB_o_oe         (io_pads_gpioB_o_oe), 

  .io_pads_qspi0_sck_i_ival   (1'b1),
  .io_pads_qspi0_sck_o_oval   (io_pads_qspi0_sck_o_oval),
  .io_pads_qspi0_sck_o_oe     (),
  .io_pads_qspi0_dq_0_i_ival  (io_pads_qspi0_dq_0_i_ival),
  .io_pads_qspi0_dq_0_o_oval  (io_pads_qspi0_dq_0_o_oval),
  .io_pads_qspi0_dq_0_o_oe    (io_pads_qspi0_dq_0_o_oe),
  .io_pads_qspi0_dq_1_i_ival  (io_pads_qspi0_dq_1_i_ival),
  .io_pads_qspi0_dq_1_o_oval  (io_pads_qspi0_dq_1_o_oval),
  .io_pads_qspi0_dq_1_o_oe    (io_pads_qspi0_dq_1_o_oe),
  .io_pads_qspi0_dq_2_i_ival  (io_pads_qspi0_dq_2_i_ival),
  .io_pads_qspi0_dq_2_o_oval  (io_pads_qspi0_dq_2_o_oval),
  .io_pads_qspi0_dq_2_o_oe    (io_pads_qspi0_dq_2_o_oe),
  .io_pads_qspi0_dq_3_i_ival  (io_pads_qspi0_dq_3_i_ival),
  .io_pads_qspi0_dq_3_o_oval  (io_pads_qspi0_dq_3_o_oval),
  .io_pads_qspi0_dq_3_o_oe    (io_pads_qspi0_dq_3_o_oe),
  .io_pads_qspi0_cs_0_i_ival  (1'b1),
  .io_pads_qspi0_cs_0_o_oval  (io_pads_qspi0_cs_0_o_oval),
  .io_pads_qspi0_cs_0_o_oe    (), 

    .hfextclk        (hfextclk),
    .hfxoscen        (hfxoscen),
    .lfextclk        (lfextclk),
    .lfxoscen        (lfxoscen),

  .io_pads_aon_erst_n_i_ival        (io_pads_aon_erst_n_i_ival       ), 
  .io_pads_aon_erst_n_o_oval        (),
  .io_pads_aon_erst_n_o_oe          (),
  .io_pads_aon_erst_n_o_ie          (),
  .io_pads_aon_erst_n_o_pue         (),
  .io_pads_aon_erst_n_o_ds          (),
  .io_pads_aon_pmu_dwakeup_n_i_ival (io_pads_aon_pmu_dwakeup_n_i_ival),
  .io_pads_aon_pmu_dwakeup_n_o_oval (),
  .io_pads_aon_pmu_dwakeup_n_o_oe   (),
  .io_pads_aon_pmu_dwakeup_n_o_ie   (),
  .io_pads_aon_pmu_dwakeup_n_o_pue  (),
  .io_pads_aon_pmu_dwakeup_n_o_ds   (),
  .io_pads_aon_pmu_vddpaden_i_ival  (1'b1 ),
  .io_pads_aon_pmu_vddpaden_o_oval  (io_pads_aon_pmu_vddpaden_o_oval ),
  .io_pads_aon_pmu_vddpaden_o_oe    (),
  .io_pads_aon_pmu_vddpaden_o_ie    (),
  .io_pads_aon_pmu_vddpaden_o_pue   (),
  .io_pads_aon_pmu_vddpaden_o_ds    (),

  
    .io_pads_aon_pmu_padrst_i_ival    (1'b1 ),
    .io_pads_aon_pmu_padrst_o_oval    (io_pads_aon_pmu_padrst_o_oval ),
    .io_pads_aon_pmu_padrst_o_oe      (),
    .io_pads_aon_pmu_padrst_o_ie      (),
    .io_pads_aon_pmu_padrst_o_pue     (),
    .io_pads_aon_pmu_padrst_o_ds      (),

    .io_pads_bootrom_n_i_ival       (io_pads_bootrom_n_i_ival),
    .io_pads_bootrom_n_o_oval       (),
    .io_pads_bootrom_n_o_oe         (),
    .io_pads_bootrom_n_o_ie         (),
    .io_pads_bootrom_n_o_pue        (),
    .io_pads_bootrom_n_o_ds         (),

    .io_pads_dbgmode0_n_i_ival       (io_pads_dbgmode0_n_i_ival),

    .io_pads_dbgmode1_n_i_ival       (io_pads_dbgmode1_n_i_ival),

    .io_pads_dbgmode2_n_i_ival       (io_pads_dbgmode2_n_i_ival) 


  );


  // =====================================================================
  // KWT-1 accelerator path:  sysper ICB  ->  icb2kwt  ->  kwt1_mmio
  //
  // Only 0x1100_0000-0x1100_FFFF is answered by icb2kwt. Any other access
  // that reaches sysper is a runaway pointer into unmapped space; the bridge
  // answers it with a one-shot rsp_err instead of silently returning zero, so
  // firmware traps instead of corrupting accelerator state.
  // =====================================================================
  icb2kwt #(
    .BASE_HI (16'h1100)
  ) u_icb2kwt (
    .clk             (hfextclk),
    .rst_n           (kwt_rst_n),

    .icb_cmd_valid   (sysper_icb_cmd_valid),
    .icb_cmd_ready   (sysper_icb_cmd_ready),
    .icb_cmd_addr    (sysper_icb_cmd_addr ),
    .icb_cmd_read    (sysper_icb_cmd_read ),
    .icb_cmd_wdata   (sysper_icb_cmd_wdata),
    .icb_cmd_wmask   (sysper_icb_cmd_wmask),

    .icb_rsp_valid   (sysper_icb_rsp_valid),
    .icb_rsp_ready   (sysper_icb_rsp_ready),
    .icb_rsp_err     (sysper_icb_rsp_err  ),
    .icb_rsp_rdata   (sysper_icb_rsp_rdata),

    .req_valid       (kwt_req_valid),
    .req_ready       (kwt_req_ready),
    .req_write       (kwt_req_write),
    .req_addr        (kwt_req_addr ),
    .req_wdata       (kwt_req_wdata),
    .req_wstrb       (kwt_req_wstrb),

    .resp_valid      (kwt_resp_valid),
    .resp_ready      (kwt_resp_ready),
    .resp_rdata      (kwt_resp_rdata),
    .resp_error      (kwt_resp_error),

    .dec_hit         ()
  );

  kwt1_mmio u_kwt1_mmio (
    .clk             (hfextclk),
    .rst_n           (kwt_rst_n),

    .abort_hw        (1'b0),   // no SoC-level abort source
    .core_enable     (1'b1),   // same tie-offs as the standalone accel TB
    .mem_enable      (1'b1),

    .req_valid       (kwt_req_valid),
    .req_ready       (kwt_req_ready),
    .req_write       (kwt_req_write),
    .req_addr        (kwt_req_addr ),
    .req_wdata       (kwt_req_wdata),
    .req_wstrb       (kwt_req_wstrb),

    .resp_valid      (kwt_resp_valid),
    .resp_ready      (kwt_resp_ready),
    .resp_rdata      (kwt_resp_rdata),
    .resp_error      (kwt_resp_error),

    .irq             (accel_irq)
  );


  // =====================================================================
  // 512 KiB system shared SRAM @0xa000_0000 (sysmem ICB port)
  //
  // Competition platform block (spec p4): "system shared SRAM is 512 KB,
  // implemented from the designated 16b x 128 / 1024 / 4096 macros"; its area
  // is reported separately and not charged to the 2.25 mm2 budget, its power
  // is charged. Here it is 64 macros of 4096 x 16, two per 4096-word page.
  //
  // The organiser's loader writes through host_* one 32-bit word per cycle;
  // the CPU sees the same array through the sysmem ICB port. The full weight
  // set is 757312 B > 512 KiB, so parameters are streamed one layer at a time
  // (61728 B lease), which the spec explicitly allows.
  // =====================================================================
  kwt_shmem #(
    .AW (17),            // 2^17 words = 512 KiB
    .DW (32)
  ) u_shmem (
    .clk       (hfextclk),
    .rst_n     (kwt_rst_n),

    .cmd_valid (sysmem_icb_cmd_valid),
    .cmd_ready (sysmem_icb_cmd_ready),
    .cmd_addr  (sysmem_icb_cmd_addr ),
    .cmd_read  (sysmem_icb_cmd_read ),
    .cmd_wdata (sysmem_icb_cmd_wdata),
    .cmd_wmask (sysmem_icb_cmd_wmask),

    .rsp_valid (sysmem_icb_rsp_valid),
    .rsp_ready (sysmem_icb_rsp_ready),
    .rsp_err   (sysmem_icb_rsp_err  ),
    .rsp_rdata (sysmem_icb_rsp_rdata),

    .host_en    (shmem_host_en   ),
    .host_addr  (shmem_host_addr ),
    .host_wdata (shmem_host_wdata)
  );

endmodule

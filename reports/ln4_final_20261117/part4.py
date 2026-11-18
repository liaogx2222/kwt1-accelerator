# -*- coding: utf-8 -*-
"""报告第四部分：第 10—12 章与附录。"""
from docx_kit import Report
import facts as F








def appendix(R: Report):
    R.h1("附录 A　MMIO 寄存器映射", new_page=True)
    R.table(
        ["偏移", "名称", "读/写", "说明"],
        [["0x00", "CTRL", "W", "写 1 启动任务；bit1 写 1 软中止"],
         ["0x04", "STATUS", "R", "bit0 busy、1 done、2 error、3 common_valid、4 input_loaded、5 layer_valid、"
                                  "6 need_parameters、7 awaiting_ack、8 start_ready、9 frame_ready、"
                                  "10 cfg_ready、11 input_ready、12 out_valid、19:16 当前层号"],
         ["0x08", "FRAME", "W", "参数帧头：bit8 = last，3:0 = kind"],
         ["0x0C", "LAST", "W", "帧尾标志，写 1 表示本包最后一个字"],
         ["0x10", "CFG_DATA", "W", "配置/权重数据，32 bit 一字"],
         ["0x14", "IN_DATA", "W", "输入数据，32 bit 一字（BLOCK_STREAM=1 时不使用）"],
         ["0x18", "OUT_DATA", "R", "输出数据，读一次前进一个地址"],
         ["0x1C", "DEBUG", "R", "{16'd0, debug_state[7:0], error_code[7:0]}"],
         ["0x20/0x24", "CYCLES", "R", "任务周期数（64 bit，低/高）"],
         ["0x28/0x2C", "COMPUTE", "R", "计算周期数"],
         ["0x30/0x34", "READS", "R", "SRAM 读次数"],
         ["0x38/0x3C", "WRITES", "R", "SRAM 写次数"],
         ["0x40/0x44", "STALLS", "R", "背压拍数"],
         ["0x48", "ID", "R", "固定 0x4B575433（“KWT3”）"]],
        widths=[2.2, 3.0, 1.8, 8.4], size=8.5, cap="加速器 MMIO 寄存器")

    R.h1("附录 B　共享 SRAM 地址划分")
    R.table(
        ["地址", "用途", "字数", "备注"],
        [["0xa000_0000", "mailbox（epoch / done 标记）", "4", "CPU与供包主设备经原总线同步"],
         ["0xa000_1000", "common 参数", "4,144", "公共配置、元信息与exp表源；按冻结schema解释"],
         ["0xa002_2000", "输出", "1,584", "99×64 INT8；NICE经原System Bus写回"],
         ["0xa002_4000", "单层参数租借区", "15,432", "61,728 B，逐层覆盖"],
         ["0xa004_0000", "输入", "3,168", "99×64 INT16，12,672 B"],
         ["0x9000_0000 起", "DTCM", "64 KiB", "平台TCM；不属于共享区，不供DMA绕行"],
         ["其余", "空闲", "—", "可容纳第二块租借区"]],
        widths=[3.4, 5.4, 2.4, 5.6], size=9, cap="共享 SRAM 划分")

    R.h1("附录 C　参数包格式", new_page=True)
    R.p("每个参数包是 32 bit 字序列，前 16 个字为帧头（含层号与形状），其后为数据，末字为 CRC-32。"
        "装载器把每个 32 bit 字拆成两个 16 bit 字，按 packet_location 写入不同bank："
        "逻辑地址 bit17 表示写私有存储，bit16:12 为bank号，bit11:0 为字地址。"
        "加载顺序固定为 common → layer_00 … layer_11，共 13 包。")
    R.table(
        ["包", "字数", "字节", "内容"],
        [["common", "4,144", "16,576", "公共配置和元信息、exp表源；层相关LN系数随层包"],
         ["layer_LL", "15,432", "61,728", "Q/K/V/O/FC1/FC2 权重、偏置、缩放与 LN 系数，按bank打包"],
         ["输入", "3,168", "12,672", "99×64 INT16"],
         ["输出", "1,584", "6,336", "99×64 INT8"]],
        widths=[2.6, 2.4, 2.4, 9.0], size=9, cap="参数包与数据包")

    R.h1("附录 D　术语")
    R.table(
        ["术语", "含义"],
        [["MAC", "乘加运算（multiply-accumulate）"],
         ["PE", "处理单元；本设计中 8×16 阵列的单个乘加单元，共 128 个"],
         ["输出驻留", "累加器常驻阵列，权重与激活流动"],
         ["RNE", "就近舍入、平局取偶（round to nearest, ties to even）"],
         ["NICE", "RISC-V 自定义指令扩展接口，本设计用于有界块搬运"],
         ["SAIF", "开关活动交换格式，门级仿真记录翻转率的标准输出"],
         ["TNS / WNS", "总负裕量 / 最差负裕量"],
         ["租借区（lease）", "共享 SRAM 中按层复用的参数缓冲区域"],
         ["晚期预取", "在 FC1 末次消费后、当前层尚未结束时装载下一层参数"]],
        widths=[3.6, 12.4], size=9, cap="术语表")

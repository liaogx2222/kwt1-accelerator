# LN4 配对综合准备状态

服务器v5入口只执行候选VCS编译及case0，成功状态为paired_vendor_RTL_cold0_passed_pending_DC_PT_and_campaign。它没有DC调用，所以其active_log是VCS日志，不能称为综合日志。用户随后已文字确认通过；原生完整日志/实际候选周期尚待程序复核。

已审查历史服务器flow/dc.tcl。它读取cache/cpu_mapped.ddc和cache/accelerator_mapped.ddc，并dont_touch旧计算模块。这不适用于包含新iterative/NICE/owner的父工程和LN4，本轮必须两份完整RTL重新综合，禁止直接运行历史脚本。

dc_from_rtl.tcl是配对综合主体。独立启动器已在deliverables/ln4_dc_pair_v1_20261116准备，7项本机控制流/证据检查和3项短传输检查通过，尚未收到服务器启动回执。它先确认v5完成并复核原始父/候选日志、矩阵、完整来源、实际编译适配文件63234e8e...及所有工具/库/约束哈希；发现新AGENTS或来源漂移应停止。不能凭本机周期或旧v6结果启动或接受当前候选。

在独立运行目录中，父和候选分别生成inputs.tcl，绑定151项实际编译输入（顶层BLOCK_STREAM1；候选核心使用声明适配文件；原件保留）、相同TT三种VT及SRAM DB、相同原服务器SDC、include路径、TOP和新的OUT。不得覆盖服务器原flow、运行或冻结交付。KWT_SIM只用于仿真，不进入综合。定义FPGA_SOURCE/SYNTHESIS/DISABLE_SV_ASSERTION/KWT_TECH_SRAM与真实数字时钟/宏绑定保持一致。

完整SoC宏数100是综合前后硬门禁，接受时再核实20私有/64共享/8ITCM/8DTCM及每个实例真实库绑定，不得以20私有宏面积冒充完整SoC面积。保存link与post_compile检查点、SVF、映射网表/DDC/SDC、原始console日志、命令、退出码及工具版本。

本阶段只有TT映射和初步setup/hold/DRC报告；recovery/removal、未约束/未测试路径、三角STA、门级campaign及同窗口功耗仍待后续，不能把compile成功或DC报告正裕量称作完整签核。脚本不增加false path、不放宽uncertainty、不改频率、不引用旧映射缓存。

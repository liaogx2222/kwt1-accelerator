"""Explicit static controller/interface register reservation, separate from data.

Lifetimes measure variable data/pipelines; these declared fields remain allocated
throughout the task, including compute. This intentionally prevents borrowing
the inactive input/FIFO/header storage during compute. Not standard-cell area.
All entries round up independently to bytes; SRAM macro output latches belong
to the macro. A byte-level controller lowering can use this layout as its cap.
"""
import math

FIELDS=[
    ('task_reset_epoch_and_completed',33),
    ('loop_counters',16*16), # token/ch/reduction/tile/pass/row/word iterators
    ('layer_stage_slot_and_valid',32),
    ('SRAM_request_addresses',20*13),
    ('SRAM_request_valid_write',20*2),
    ('SRAM_write_holding_words',20*16),
    ('packet_header',64*8),
    ('packet_FIFO',8*(5+13+16+1)), # bank/address/data/valid, bit packed
    ('packet_FIFO_pointers_and_count',3*4),
    ('packet_position_and_lengths',4*32),
    ('packet_CRC_header_and_body',2*32),
    ('packet_descriptor_comparator_word',32),
    ('packet_source_holding_word_and_last',33),
    ('input_pair_buffer',128*8),
    ('input_pair_counters',3*8),
    ('output_holding_word_and_valid',33),
    ('output_gather_word_and_count',32+3),
    ('wide_pipeline_valid_and_mode',3*5),
    ('divider_sqrt_control',2*(7+3)),
    ('PE_mode_and_lane_mask',16),
]


def static_layout():
    offset=0;rows=[]
    for name,bits in FIELDS:
        size=math.ceil(bits/8);rows.append({'field':name,'bits':bits,'bytes':size,'offset':offset});offset+=size
    return {'fields':rows,'bytes':offset,'lifetime':'entire task, conservatively including compute'}


def budget(liveness):
    fixed=static_layout()['bytes'];peak=liveness['peak_bytes']+fixed
    return {'data_and_inflight_peak_bytes':liveness['peak_bytes'],'static_control_interface_bytes':fixed,
            'reserved_total_peak_bytes':peak,'budget_bytes':4096,'remaining_bytes':4096-peak,'passed':peak<=4096,
            'scope':'declared register layout plus measured variable lifetimes; no physical register placement claim'}

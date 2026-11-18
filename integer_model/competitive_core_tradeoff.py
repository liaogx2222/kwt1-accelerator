"""Explicit accumulator-capacity alternative, unchanged integer arithmetic."""
from .competitive_resident_core import ResidentCore


class TradeoffCore(ResidentCore):
    def __init__(self,exp_table,lanes=4,beat_cycles=1,accumulator_buffers=2):
        if accumulator_buffers not in [1,2]:raise ValueError('buffer capacity')
        self.accumulator_buffers=accumulator_buffers;self.capacity_wait=0
        super().__init__(exp_table,lanes,beat_cycles)
    def reset(self):
        config=self.config;buffers=self.accumulator_buffers;self.__init__(*config,accumulator_buffers=buffers)
    def credit(self):
        if self.accumulator_buffers==1:
            while self.jobs:self.capacity_wait+=1;self.e.step(1,'single_accumulator_credit_wait')
    def mac(self,*a,**k):self.credit();return super().mac(*a,**k)
    def raw_mac(self,*a,**k):self.credit();return super().raw_mac(*a,**k)
    def summary(self):
        result=super().summary();result.update(accumulator_buffers=self.accumulator_buffers,vector_lanes=self.lanes,
            accumulator_capacity_wait_cycles=self.capacity_wait)
        return result

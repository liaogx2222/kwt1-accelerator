"""A reset cancels the old compute owner without clearing SRAM or new-task I/O."""
class TaskBanks:
    def __init__(self,banks):
        object.__setattr__(self,'_banks',banks);object.__setattr__(self,'_epoch',banks.task_epoch)
    def __getattr__(self,name):return getattr(self._banks,name)
    def __setattr__(self,name,value):self.check();setattr(self._banks,name,value)
    def check(self):
        if self._epoch!=self._banks.task_epoch:raise RuntimeError('compute aborted by task reset')
    def tick(self,*args,**kwargs):
        self.check();result=self._banks.tick(*args,**kwargs);self.check();return result
    def idle(self,*args,**kwargs):
        self.check();result=self._banks.idle(*args,**kwargs);self.check();return result
    def peek_word(self,*args,**kwargs):self.check();return self._banks.peek_word(*args,**kwargs)

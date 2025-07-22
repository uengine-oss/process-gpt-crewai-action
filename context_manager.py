from contextvars import ContextVar
from typing import Optional

todo_id_var: ContextVar[Optional[int]] = ContextVar('todo_id', default=None)
proc_id_var: ContextVar[Optional[str]] = ContextVar('proc_inst_id', default=None) 
import abc
from _typeshed import Incomplete
from arctic._config import ARCTIC_ASYNC_NWORKERS as ARCTIC_ASYNC_NWORKERS
from arctic.exceptions import AsyncArcticException as AsyncArcticException

ABC: Incomplete

def _looping_task(shutdown_flag, fun, *args, **kwargs) -> None: ...
def _exec_task(fun, *args, **kwargs) -> None: ...

class LazySingletonTasksCoordinator(ABC, metaclass=abc.ABCMeta):
    _instance: Incomplete
    _SINGLETON_LOCK: Incomplete
    _POOL_LOCK: Incomplete
    @classmethod
    def is_initialized(cls): ...
    @classmethod
    def get_instance(cls, pool_size: Incomplete | None = ...): ...
    _pool: Incomplete
    @property
    def _workers_pool(self): ...
    _lock: Incomplete
    _pool_size: Incomplete
    _pool_update_hooks: Incomplete
    alive_tasks: Incomplete
    is_shutdown: bool
    def __init__(self, pool_size) -> None: ...
    def reset(self, pool_size: Incomplete | None = ..., timeout: Incomplete | None = ...) -> None: ...
    def stop_all_running_tasks(self) -> None: ...
    @staticmethod
    def wait_tasks(futures, timeout: Incomplete | None = ..., return_when=..., raise_exceptions: bool = ...) -> None: ...
    @staticmethod
    def wait_tasks_or_abort(futures, timeout: int = ..., kill_switch_ev: Incomplete | None = ...) -> None: ...
    def register_update_hook(self, fun) -> None: ...
    def submit_task(self, is_looping, fun, *args, **kwargs): ...
    def total_alive_tasks(self): ...
    def shutdown(self, timeout: Incomplete | None = ...) -> None: ...
    def await_termination(self, timeout: Incomplete | None = ...) -> None: ...
    @property
    def actual_pool_size(self): ...
    @abc.abstractmethod
    def __reduce__(self): ...

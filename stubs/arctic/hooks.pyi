from _typeshed import Incomplete

_resolve_mongodb_hook: Incomplete
_log_exception_hook: Incomplete
_get_auth_hook: Incomplete

def get_mongodb_uri(host): ...
def register_resolve_mongodb_hook(hook) -> None: ...
def log_exception(fn_name, exception, retry_count, **kwargs) -> None: ...
def register_log_exception_hook(hook) -> None: ...
def register_get_auth_hook(hook) -> None: ...

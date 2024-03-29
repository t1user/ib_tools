from _typeshed import Incomplete
from enum import Enum

logger: Incomplete
STRICT_WRITE_HANDLER_MATCH: Incomplete
CHECK_CORRUPTION_ON_APPEND: Incomplete
ARCTIC_AUTO_EXPAND_CHUNK_SIZE: Incomplete
MAX_DOCUMENT_SIZE: Incomplete
FAST_CHECK_DF_SERIALIZABLE: Incomplete

class FwPointersCfg(Enum):
    ENABLED: int
    DISABLED: int
    HYBRID: int

FW_POINTERS_REFS_KEY: str
FW_POINTERS_CONFIG_KEY: str
ARCTIC_FORWARD_POINTERS_RECONCILE: bool
ARCTIC_FORWARD_POINTERS_CFG: Incomplete
ENABLE_PARALLEL: Incomplete
LZ4_HIGH_COMPRESSION: Incomplete
LZ4_WORKERS: Incomplete
LZ4_N_PARALLEL: Incomplete
LZ4_MINSZ_PARALLEL: Incomplete
BENCHMARK_MODE: bool
ARCTIC_ASYNC_NWORKERS: Incomplete
FORCE_BYTES_TO_UNICODE: Incomplete
ENABLE_CACHE: Incomplete
SKIP_BSON_ENCODE_PICKLE_STORE: Incomplete
MAX_BSON_ENCODE: Incomplete

from ..chunkstore.chunkstore import CHUNK_STORE_TYPE as CHUNK_STORE_TYPE
from ..store.bitemporal_store import BitemporalStore as BitemporalStore
from ..tickstore.tickstore import TICK_STORE_TYPE as TICK_STORE_TYPE
from _typeshed import Incomplete

logger: Incomplete

def mongo_host(mongo_server): ...
def arctic(mongo_server): ...
def arctic_secondary(mongo_server, arctic): ...
def multicolumn_store_with_uncompressed_write(mongo_server): ...
def ndarray_store_with_uncompressed_write(mongo_server): ...
def library_name(): ...
def user_library_name(): ...
def overlay_library_name(): ...
def library(arctic, library_name): ...
def bitemporal_library(arctic, library_name): ...
def library_secondary(arctic_secondary, library_name): ...
def user_library(arctic, user_library_name): ...
def overlay_library(arctic, overlay_library_name): ...
def _overlay_library(arctic, overlay_library_name): ...
def tickstore_lib(arctic, library_name): ...
def _tickstore_lib(arctic, library_name): ...
def chunkstore_lib(arctic, library_name): ...
def ms_lib(arctic, library_name): ...

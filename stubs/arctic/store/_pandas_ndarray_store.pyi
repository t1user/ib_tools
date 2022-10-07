from .._compression import compress as compress, decompress as decompress
from .._config import FORCE_BYTES_TO_UNICODE as FORCE_BYTES_TO_UNICODE
from ..date._util import to_pandas_closed_closed as to_pandas_closed_closed
from ..exceptions import ArcticException as ArcticException
from ._ndarray_store import NdarrayStore as NdarrayStore
from _typeshed import Incomplete
from arctic._util import NP_OBJECT_DTYPE as NP_OBJECT_DTYPE
from arctic.serialization.numpy_records import DataFrameSerializer as DataFrameSerializer, SeriesSerializer as SeriesSerializer

log: Incomplete
DTN64_DTYPE: str
INDEX_DTYPE: Incomplete

class PandasStore(NdarrayStore):
    def _segment_index(self, recarr, existing_index, start, new_segments): ...
    def _datetime64_index(self, recarr): ...
    def read_options(self): ...
    def _index_range(self, version, symbol, date_range: Incomplete | None = ..., **kwargs): ...
    def _daterange(self, recarr, date_range): ...
    def read(self, arctic_lib, version, symbol, read_preference: Incomplete | None = ..., date_range: Incomplete | None = ..., **kwargs): ...
    def get_info(self, version): ...

def _start_end(date_range, dts): ...
def _assert_no_timezone(date_range) -> None: ...

class PandasSeriesStore(PandasStore):
    TYPE: str
    SERIALIZER: Incomplete
    @staticmethod
    def can_write_type(data): ...
    def can_write(self, version, symbol, data): ...
    def write(self, arctic_lib, version, symbol, item, previous_version) -> None: ...
    def append(self, arctic_lib, version, symbol, item, previous_version, **kwargs) -> None: ...
    def read_options(self): ...
    def read(self, arctic_lib, version, symbol, **kwargs): ...

class PandasDataFrameStore(PandasStore):
    TYPE: str
    SERIALIZER: Incomplete
    @staticmethod
    def can_write_type(data): ...
    def can_write(self, version, symbol, data): ...
    def write(self, arctic_lib, version, symbol, item, previous_version) -> None: ...
    def append(self, arctic_lib, version, symbol, item, previous_version, **kwargs) -> None: ...
    def read(self, arctic_lib, version, symbol, **kwargs): ...
    def read_options(self): ...

class PandasPanelStore(PandasDataFrameStore):
    TYPE: str
    @staticmethod
    def can_write_type(data): ...
    def can_write(self, version, symbol, data): ...
    def write(self, arctic_lib, version, symbol, item, previous_version) -> None: ...
    def read(self, arctic_lib, version, symbol, **kwargs): ...
    def read_options(self): ...
    def append(self, arctic_lib, version, symbol, item, previous_version, **kwargs) -> None: ...
class ArcticException(Exception): ...
class NoDataFoundException(ArcticException): ...
class UnhandledDtypeException(ArcticException): ...
class LibraryNotFoundException(ArcticException): ...
class DuplicateSnapshotException(ArcticException): ...
class StoreNotInitializedException(ArcticException): ...
class OptimisticLockException(ArcticException): ...
class QuotaExceededException(ArcticException): ...
class UnsupportedPickleStoreVersion(ArcticException): ...
class DataIntegrityException(ArcticException): ...
class ArcticSerializationException(ArcticException): ...
class ConcurrentModificationException(DataIntegrityException): ...
class UnorderedDataException(DataIntegrityException): ...
class OverlappingDataException(DataIntegrityException): ...
class AsyncArcticException(ArcticException): ...
class RequestDurationException(AsyncArcticException): ...

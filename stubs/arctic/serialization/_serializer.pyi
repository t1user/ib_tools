class Serializer:
    def serialize(self, data, **kwargs) -> None: ...
    def deserialize(self, data, **kwargs) -> None: ...
    def combine(self, a, b) -> None: ...

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Generic, Iterable, TypeVar

T = TypeVar("T")


@dataclass
class ComponentRegistry(Generic[T]):
    _items: dict[str, T] = field(default_factory=dict)

    def register(self, name: str, item: T) -> None:
        if name in self._items:
            raise KeyError(f"Component already registered: {name}")
        self._items[name] = item

    def decorator(self, name: str) -> Callable[[T], T]:
        def _wrap(item: T) -> T:
            self.register(name, item)
            return item

        return _wrap

    def get(self, name: str) -> T:
        if name not in self._items:
            raise KeyError(f"Component not registered: {name}")
        return self._items[name]

    def all(self) -> dict[str, T]:
        return dict(self._items)

    def names(self) -> Iterable[str]:
        return tuple(self._items.keys())


fetchers: ComponentRegistry[Callable[..., object]] = ComponentRegistry()
extractors: ComponentRegistry[Callable[..., object]] = ComponentRegistry()
ai_providers: ComponentRegistry[Callable[..., object]] = ComponentRegistry()
sinks: ComponentRegistry[Callable[..., object]] = ComponentRegistry()

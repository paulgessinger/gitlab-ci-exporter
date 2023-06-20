import abc
from typing import List

from prometheus_client import CollectorRegistry


class Updater(abc.ABC):
    @abc.abstractmethod
    async def tick(self, projects: List[str]) -> None:
        raise NotImplemented()

    registry: CollectorRegistry

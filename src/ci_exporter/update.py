import abc

from prometheus_client import CollectorRegistry

class Updater(abc.ABC):
    @abc.abstractmethod
    def tick(self, project: str) -> None:
        raise NotImplemented()


    registry: CollectorRegistry

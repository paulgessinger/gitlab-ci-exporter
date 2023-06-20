import abc

class Updater(abc.ABC):
    @abc.abstractmethod
    def tick(self, project: str) -> None:
        raise NotImplemented()

from abc import ABC, abstractmethod
from telegram.ext import Application


class BaseModule(ABC):
    def __init__(self, config: dict):
        self.config = config
        self.name   = self.__class__.__name__

    @abstractmethod
    def setup(self, app: Application) -> None:
        pass

    def on_load(self) -> None:
        print(f"[✅ 模块加载] {self.name}")

    def on_unload(self) -> None:
        print(f"[❌ 模块卸载] {self.name}")

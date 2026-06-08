import logging
from abc import ABC, abstractmethod

from telegram.ext import Application

logger = logging.getLogger("shuangxiang.module")


class BaseModule(ABC):
    def __init__(self, config: dict):
        self.config = config
        self.name   = self.__class__.__name__

    @abstractmethod
    def setup(self, app: Application) -> None:
        pass

    def on_load(self) -> None:
        logger.info("[模块加载] %s", self.name)


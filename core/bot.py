import logging

from core.app_factory import build_application
from core.loader import ModuleLoader

logger = logging.getLogger("shuangxiang.bot")


class ModularBot:

    def __init__(self, config: dict):
        self.config = config
        self.token  = config["bot"]["token"]
        self.app    = build_application(self.token)
        self.loader = ModuleLoader(self.config)
        self._setup()

    def _setup(self) -> None:
        logger.info("正在加载模块...")
        self.loader.load_all(self.app)
        logger.info("已加载 %d 个模块", len(self.loader.list_modules()))


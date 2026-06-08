import importlib
from core.base_module import BaseModule
from telegram.ext import Application


class ModuleLoader:
    def __init__(self, config: dict):
        self.config = config
        self.loaded_modules: dict[str, BaseModule] = {}

    def load_module(self, module_path: str, app: Application) -> None:
        try:
            mod        = importlib.import_module(module_path)
            class_name = "".join(w.capitalize() for w in module_path.split(".")[-1].split("_"))
            cls        = getattr(mod, class_name)
            instance: BaseModule = cls(self.config)
            instance.setup(app)
            instance.on_load()
            self.loaded_modules[module_path] = instance
        except Exception as e:
            print(f"[❌ 加载失败] {module_path}: {e}")

    def load_all(self, app: Application) -> None:
        for module_path in self.config.get("modules", []):
            self.load_module(module_path, app)

    def list_modules(self) -> list[str]:
        return list(self.loaded_modules.keys())

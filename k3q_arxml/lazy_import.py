from importlib import import_module


class LazyImport:
    def __init__(self, module_name):
        self._module_name = module_name
        self._module = None

    def __getattr__(self, attr):
        if self._module is None:
            self._module = import_module(self._module_name)
        return getattr(self._module, attr)

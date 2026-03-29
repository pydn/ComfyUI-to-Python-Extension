from typing import Dict


class LoadOrderDeterminer:
    """Determine workflow execution order with loader-like nodes prioritized."""

    def __init__(self, data: Dict, node_class_mappings: Dict):
        self.data = data
        self.node_class_mappings = node_class_mappings
        self.visited = {}
        self.load_order = []
        self.is_special_function = False

    def determine_load_order(self) -> list[tuple[str, Dict, bool]]:
        self._load_special_functions_first()
        self.is_special_function = False
        for key in self.data:
            if key not in self.visited:
                self._dfs(key)
        return self.load_order

    def _dfs(self, key: str) -> None:
        self.visited[key] = True
        inputs = self.data[key]["inputs"]
        for value in inputs.values():
            if isinstance(value, list) and value[0] not in self.visited:
                self._dfs(value[0])
        self.load_order.append((key, self.data[key], self.is_special_function))

    def _load_special_functions_first(self) -> None:
        for key in self.data:
            class_def = self.node_class_mappings[self.data[key]["class_type"]]()
            if (
                class_def.CATEGORY == "loaders"
                or class_def.FUNCTION in ["encode"]
                or not any(
                    isinstance(value, list)
                    for value in self.data[key]["inputs"].values()
                )
            ):
                self.is_special_function = True
                if key not in self.visited:
                    self._dfs(key)

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class HistoryStack:
    limit: int = 20
    undo_stack: list[Path] = field(default_factory=list)
    redo_stack: list[Path] = field(default_factory=list)

    def push(self, snapshot: Path) -> None:
        self.undo_stack.append(snapshot)
        if len(self.undo_stack) > self.limit:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    def can_redo(self) -> bool:
        return bool(self.redo_stack)

    def undo(self, current_snapshot: Path | None = None) -> Path | None:
        if not self.undo_stack:
            return None
        if current_snapshot is not None:
            self.redo_stack.append(current_snapshot)
        return self.undo_stack.pop()

    def redo(self, current_snapshot: Path | None = None) -> Path | None:
        if not self.redo_stack:
            return None
        if current_snapshot is not None:
            self.undo_stack.append(current_snapshot)
            if len(self.undo_stack) > self.limit:
                self.undo_stack.pop(0)
        return self.redo_stack.pop()

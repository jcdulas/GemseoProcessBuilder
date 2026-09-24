"""The edited project, its revisions, its undo history and its changes.

The page keeps a flat mirror of the document (SPEC § 3.5): every node, link and
layout entry is an entity identified by ``(kind, id)``. Each command produces a
list of changes for the entities it touched, and increments the revision.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from gemseo_process_builder.core.commands import Command
from gemseo_process_builder.core.commands import CommandError
from gemseo_process_builder.core.commands import Effect
from gemseo_process_builder.core.commands import EntityKey
from gemseo_process_builder.core.commands import MoveNodes
from gemseo_process_builder.core.model import AssemblyNode
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import Node
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.model import iter_nodes

MERGE_DELAY_S = 0.5
"""Consecutive moves of the same nodes within this delay form one undo entry."""

Change = dict[str, Any]
ChangeListener = Callable[[list[Change], int], None]


def node_entity(node: Node, parent_id: str | None) -> dict[str, Any]:
    """The flat form of a node sent to the page: children are ids."""
    data = node.model_dump(mode="json", exclude={"children"})
    data["parent"] = parent_id
    if isinstance(node, AssemblyNode | DriverNode):
        data["children"] = [child.id for child in node.children]
    return data


def entity_data(project: Project, key: EntityKey) -> Any:
    """Return the current data of an entity, or ``None`` if it does not exist."""
    kind, entity_id = key
    if kind == "node":
        for node, parent in iter_nodes(project.root):
            if node.id == entity_id:
                return node_entity(node, parent.id if parent else None)
        return None
    if kind == "link":
        for link in project.links:
            if link.id == entity_id:
                return link.model_dump(mode="json")
        return None
    if kind == "layout":
        layout = project.layout.nodes.get(entity_id)
        return layout.model_dump(mode="json") if layout else None
    if kind == "level":
        level = project.layout.levels.get(entity_id)
        return level.model_dump(mode="json") if level else None
    if kind == "view":
        if entity_id == "tree_expanded":
            return project.layout.tree_expanded
        return project.layout.extra.get(entity_id.removeprefix("extra."))
    msg = f"Unknown entity kind {kind!r}."
    raise ValueError(msg)


def snapshot(project: Project, rev: int) -> dict[str, Any]:
    """The whole document in the flat form used by the page."""
    return {
        "rev": rev,
        "root": project.root.id,
        "nodes": {
            node.id: node_entity(node, parent.id if parent else None)
            for node, parent in iter_nodes(project.root)
        },
        "links": {link.id: link.model_dump(mode="json") for link in project.links},
        "layout": {
            node_id: layout.model_dump(mode="json")
            for node_id, layout in project.layout.nodes.items()
        },
        "levels": {
            level: transform.model_dump(mode="json")
            for level, transform in project.layout.levels.items()
        },
        "view": {
            "tree_expanded": project.layout.tree_expanded,
            **{f"extra.{key}": value for key, value in project.layout.extra.items()},
        },
        "project": {
            "metadata": project.metadata.model_dump(mode="json"),
            "settings": project.settings.model_dump(mode="json"),
        },
    }


@dataclass
class UndoEntry:
    """One step of the undo history, made of one or more commands."""

    label: str
    inverses: list[Command] = field(default_factory=list)
    """The commands undoing the step, in the order the step applied them."""

    time: float = 0.0
    merge_key: frozenset[str] | None = None


@dataclass
class RedoEntry:
    """One undone step, ready to be redone."""

    label: str
    commands: list[Command]


class Document:
    """A project edited through commands.

    Args:
        project: The project to edit.
        max_undo: The number of undo steps kept.
        clock: Returns the current time in seconds (replaced in tests).
    """

    def __init__(
        self,
        project: Project,
        max_undo: int = 500,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.project = project
        self.max_undo = max_undo
        self.rev = 0
        self._clock = clock
        self._undo: list[UndoEntry] = []
        self._redo: list[RedoEntry] = []
        self._transaction: UndoEntry | None = None
        self._transaction_depth = 0
        self._pending: set[EntityKey] = set()
        self._listeners: list[ChangeListener] = []

    # Listeners -----------------------------------------------------------------

    def on_change(self, listener: ChangeListener) -> None:
        """Call ``listener(changes, rev)`` after each change of the document."""
        self._listeners.append(listener)

    def reset(self, project: Project) -> None:
        """Replace the project; the undo history is cleared."""
        self.project = project
        self.rev += 1
        self._undo.clear()
        self._redo.clear()

    def snapshot(self) -> dict[str, Any]:
        """The whole document in the flat form used by the page."""
        return snapshot(self.project, self.rev)

    # Editing -------------------------------------------------------------------

    def execute(self, command: Command, undoable: bool = True) -> int:
        """Apply a command and return the new revision.

        Raises:
            CommandError: When the command cannot be applied; nothing changes.
        """
        effect = command.apply(self.project)
        if undoable:
            self._record(command, effect)
        self._pending |= effect.touched | effect.removed
        if self._transaction is None:
            self._publish()
        return self.rev

    def execute_many(self, commands: list[Command], label: str) -> int:
        """Apply several commands as one undo step; all or nothing."""
        self.begin(label)
        try:
            for command in commands:
                self.execute(command)
        except CommandError:
            self.rollback()
            raise
        self.commit()
        return self.rev

    def begin(self, label: str) -> None:
        """Start grouping commands into one undo step (transactions nest)."""
        if self._transaction is None:
            self._transaction = UndoEntry(label=label, time=self._clock())
        self._transaction_depth += 1

    def commit(self) -> None:
        """End a group of commands."""
        self._transaction_depth -= 1
        if self._transaction_depth > 0 or self._transaction is None:
            return
        entry, self._transaction = self._transaction, None
        if entry.inverses:
            self._push(entry)
        self._publish()

    def rollback(self) -> None:
        """Undo the commands of the current group and forget it."""
        entry, self._transaction = self._transaction, None
        self._transaction_depth = 0
        if entry is not None:
            for inverse in reversed(entry.inverses):
                effect = inverse.apply(self.project)
                self._pending |= effect.touched | effect.removed
        self._publish()

    def _record(self, command: Command, effect: Effect) -> None:
        if self._transaction is not None:
            self._transaction.inverses.append(effect.inverse)
            return
        merge_key = (
            frozenset(command.positions) if isinstance(command, MoveNodes) else None
        )
        now = self._clock()
        last = self._undo[-1] if self._undo else None
        if (
            merge_key is not None
            and last is not None
            and last.merge_key == merge_key
            and now - last.time < MERGE_DELAY_S
        ):
            last.time = now  # Keep the original positions as the undo target.
            self._redo.clear()
            return
        self._push(
            UndoEntry(
                label=command.label,
                inverses=[effect.inverse],
                time=now,
                merge_key=merge_key,
            )
        )

    def _push(self, entry: UndoEntry) -> None:
        self._undo.append(entry)
        del self._undo[: -self.max_undo]
        self._redo.clear()

    # Undo and redo -------------------------------------------------------------

    def undo(self) -> int:
        """Undo the last step and return the new revision."""
        if not self._undo:
            return self.rev
        entry = self._undo.pop()
        effects = [inverse.apply(self.project) for inverse in reversed(entry.inverses)]
        self._redo.append(
            RedoEntry(
                label=entry.label,
                commands=[effect.inverse for effect in reversed(effects)],
            )
        )
        for effect in effects:
            self._pending |= effect.touched | effect.removed
        self._publish()
        return self.rev

    def redo(self) -> int:
        """Redo the last undone step and return the new revision."""
        if not self._redo:
            return self.rev
        entry = self._redo.pop()
        effects = [command.apply(self.project) for command in entry.commands]
        self._undo.append(
            UndoEntry(
                label=entry.label,
                inverses=[effect.inverse for effect in effects],
                time=self._clock(),
            )
        )
        for effect in effects:
            self._pending |= effect.touched | effect.removed
        self._publish()
        return self.rev

    def undo_state(self) -> dict[str, Any]:
        """Whether undo and redo are possible, and their labels."""
        return {
            "canUndo": bool(self._undo),
            "canRedo": bool(self._redo),
            "undoLabel": self._undo[-1].label if self._undo else "",
            "redoLabel": self._redo[-1].label if self._redo else "",
        }

    # Changes -------------------------------------------------------------------

    def _publish(self) -> None:
        if not self._pending:
            return
        changes: list[Change] = []
        for key in sorted(self._pending):
            data = entity_data(self.project, key)
            kind, entity_id = key
            if data is None:
                changes.append({"op": "delete", "kind": kind, "id": entity_id})
            else:
                changes.append(
                    {"op": "upsert", "kind": kind, "id": entity_id, "data": data}
                )
        self._pending.clear()
        self.rev += 1
        for listener in self._listeners:
            listener(changes, self.rev)

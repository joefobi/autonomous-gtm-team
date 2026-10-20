"""Typed adapter for the installed Band command-line interface."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class BandCommandError(RuntimeError):
    """Raised when a Band command cannot complete."""


@dataclass(frozen=True, slots=True)
class BandCommandResult:
    """Result returned by one Band command."""

    command: tuple[str, ...]
    stdout: str
    stderr: str
    returncode: int


@dataclass(frozen=True, slots=True)
class SharedTask:
    """Task visible on a Band room's shared board."""

    uid: str
    subject: str
    detail: str
    status: str
    owners: tuple[str, ...]
    completion_evidence: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> SharedTask:
        """Build a shared task from Band JSON.

        Args:
            payload: Decoded Band task object.

        Returns:
            A normalized shared task.
        """
        uid = _required_text(
            payload.get("uid", payload.get("id", payload.get("task_id"))),
            "task uid",
        )
        subject = _required_text(
            payload.get("subject", payload.get("title")), "task subject"
        )
        detail = _optional_text(payload.get("detail")) or ""
        status = _optional_text(payload.get("status")) or "pending"
        owners = _owners(payload.get("owners", payload.get("assignees")))
        completion_evidence = _optional_text(
            payload.get("completion_evidence", payload.get("evidence"))
        )
        return cls(uid, subject, detail, status, owners, completion_evidence)


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class BandClient:
    """Invoke documented Band CLI commands for a configured agent."""

    def __init__(
        self,
        executable: str = "band",
        cwd: Path | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        """Initialize a Band CLI client.

        Args:
            executable: Band executable name or absolute path.
            cwd: Working directory for Band commands.
            runner: Optional subprocess-compatible runner for tests.
        """
        self.executable = executable
        self.cwd = cwd
        self._runner = runner or subprocess.run

    def set_plan(
        self,
        room_id: str,
        source: Path,
        strategist_handle: str,
        snapshot: bool = True,
    ) -> BandCommandResult:
        """Attach the strategist-owned plan to a room.

        Args:
            room_id: Band room identifier.
            source: Markdown plan path.
            strategist_handle: Band handle publishing the plan.
            snapshot: Store a durable Band copy when true.

        Returns:
            The Band command result.
        """
        arguments = ["plan", "set", room_id, str(source)]
        if snapshot:
            arguments.append("--snapshot")
        return self._run(arguments, strategist_handle)

    def assign_task(
        self,
        room_id: str,
        subject: str,
        detail: str,
        strategist_handle: str,
        components: Sequence[str] = (),
    ) -> BandCommandResult:
        """Create a shared task owned by the strategist.

        Args:
            room_id: Band room identifier.
            subject: Task headline.
            detail: Task scope and completion evidence.
            strategist_handle: Band handle assigning the task.
            components: Optional architecture node identifiers.

        Returns:
            The Band command result.
        """
        arguments = ["work", "assign", room_id, subject, "--detail", detail]
        for component in components:
            arguments.extend(("--component", component))
        return self._run(arguments, strategist_handle)

    def board(self, room_id: str, strategist_handle: str) -> tuple[SharedTask, ...]:
        """Read the shared task board.

        Args:
            room_id: Band room identifier.
            strategist_handle: Band handle reading the board.

        Returns:
            Shared tasks in the room.
        """
        payload = self._json_run(
            ["work", "board", room_id, "--json"], strategist_handle
        )
        raw_tasks: object = payload.get("tasks", payload.get("items", payload))
        if not isinstance(raw_tasks, list):
            raise BandCommandError("Band board JSON has no task list")
        tasks: list[SharedTask] = []
        for raw_task in raw_tasks:
            if not isinstance(raw_task, dict):
                raise BandCommandError("Band board JSON contains an invalid task")
            tasks.append(SharedTask.from_mapping(raw_task))
        return tuple(tasks)

    def take_task(
        self, room_id: str, task_uid: str, researcher_handle: str
    ) -> BandCommandResult:
        """Assign a researcher to a shared task.

        Args:
            room_id: Band room identifier.
            task_uid: Shared task UID such as `#3`.
            researcher_handle: Band handle taking the task.

        Returns:
            The Band command result.
        """
        return self._run(["work", "take", room_id, task_uid], researcher_handle)

    def set_task_status(
        self,
        room_id: str,
        task_uid: str,
        status: str,
        agent_handle: str,
    ) -> BandCommandResult:
        """Update an agent's status on a shared task.

        Args:
            room_id: Band room identifier.
            task_uid: Shared task UID such as `#3`.
            status: Band status such as `in_progress` or `completed`.
            agent_handle: Band handle changing its assignment status.

        Returns:
            The Band command result.
        """
        return self._run(
            ["work", "room-status", room_id, task_uid, status], agent_handle
        )

    def edit_task(
        self,
        room_id: str,
        task_uid: str,
        detail: str,
        agent_handle: str,
    ) -> BandCommandResult:
        """Record completion evidence on a shared task.

        Args:
            room_id: Band room identifier.
            task_uid: Shared task UID such as `#3`.
            detail: Updated task detail with completion evidence.
            agent_handle: Band handle editing the task.

        Returns:
            The Band command result.
        """
        return self._run(
            ["work", "edit", room_id, task_uid, "--detail", detail], agent_handle
        )

    def send_message(
        self,
        room_id: str,
        message: str,
        sender_handle: str,
    ) -> BandCommandResult:
        """Send a message into a Band room.

        Args:
            room_id: Band room identifier.
            message: Message body with an explicit recipient mention.
            sender_handle: Band handle sending the message.

        Returns:
            The Band command result.
        """
        return self._run(["send", room_id, message], sender_handle)

    def add_participant(
        self,
        room_id: str,
        participant_handle: str,
        inviter_handle: str,
    ) -> BandCommandResult:
        """Add an agent to a Band room.

        Args:
            room_id: Band room identifier.
            participant_handle: Band handle to add.
            inviter_handle: Band handle performing the addition.

        Returns:
            The Band command result.
        """
        return self._run(["chat", "add", room_id, participant_handle], inviter_handle)

    def ask_founder(
        self,
        prompt: str,
        options: Sequence[str],
        strategist_handle: str,
    ) -> dict[str, object]:
        """Ask the founder a structured question through Band.

        Args:
            prompt: Decision question shown to the founder.
            options: Selectable decision options.
            strategist_handle: Band handle asking the question.

        Returns:
            Decoded Band answer payload.
        """
        arguments = ["ask", "--prompt", prompt, "--json"]
        for option in options:
            arguments.extend(("--option", option))
        return self._json_run(arguments, strategist_handle)

    def _run(
        self, arguments: Sequence[str], agent_handle: str | None = None
    ) -> BandCommandResult:
        """Run one Band command and validate its exit code.

        Args:
            arguments: Band subcommand arguments.
            agent_handle: Optional peer handle for the `--as` selector.

        Returns:
            The completed Band command.
        """
        command = [self.executable, *arguments]
        if agent_handle:
            command.extend(("--as", agent_handle))
        completed = self._runner(
            command,
            cwd=str(self.cwd) if self.cwd is not None else None,
            text=True,
            capture_output=True,
            check=False,
        )
        result = BandCommandResult(
            tuple(command), completed.stdout, completed.stderr, completed.returncode
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise BandCommandError(f"Band command failed: {detail}")
        return result

    def _json_run(
        self, arguments: Sequence[str], agent_handle: str | None = None
    ) -> dict[str, object]:
        """Run a Band command and decode an object response.

        Args:
            arguments: Band subcommand arguments.
            agent_handle: Optional peer handle for the `--as` selector.

        Returns:
            Decoded JSON object.
        """
        result = self._run(arguments, agent_handle)
        try:
            payload: object = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise BandCommandError("Band command returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise BandCommandError("Band command returned a non-object JSON value")
        return payload


def _required_text(value: object, field_name: str) -> str:
    """Return required task text.

    Args:
        value: Candidate value.
        field_name: Field label.

    Returns:
        Normalized text.
    """
    text = _optional_text(value)
    if text is None:
        raise BandCommandError(f"Band task is missing {field_name}")
    return text


def _optional_text(value: object) -> str | None:
    """Normalize optional text.

    Args:
        value: Candidate value.

    Returns:
        Normalized text or `None`.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _owners(value: object) -> tuple[str, ...]:
    """Normalize Band task owners.

    Args:
        value: Owner collection from Band JSON.

    Returns:
        Owner handles.
    """
    if not isinstance(value, list):
        return ()
    owners: list[str] = []
    for owner in value:
        if isinstance(owner, str) and owner.strip():
            owners.append(owner.strip())
        elif isinstance(owner, dict):
            handle = owner.get("handle")
            if isinstance(handle, str) and handle.strip():
                owners.append(handle.strip())
    return tuple(owners)

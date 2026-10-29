"""Approval gate for outward actions. Jarvis proposes; only the user's own reply approves.

The model never calls approve(): the Hermes plugin calls it when the user's message is a clear
yes, so a model that skips asking cannot get an action through.
"""
import json
import re

import psycopg
from psycopg.rows import dict_row

from . import config

_YES = re.compile(r"^\s*(yes|y|yeah|yep|ok|okay|sure|confirm|confirmed|go ahead|do it|add it|please do)\b[\s.!]*$", re.I)


def propose(kind: str, payload: dict, summary: str) -> dict:
    with psycopg.connect(config.DB_DSN, row_factory=dict_row) as conn:
        # Only the newest proposal can be approved; older unapproved ones lapse.
        conn.execute("UPDATE pending_actions SET result = '{\"lapsed\": true}' WHERE approved_at IS NULL AND executed_at IS NULL AND result IS NULL")
        row = conn.execute(
            "INSERT INTO pending_actions (kind, payload, summary) VALUES (%s, %s, %s) RETURNING id, summary",
            (kind, json.dumps(payload), summary),
        ).fetchone()
    return row


def approve_from_user_message(message: str) -> int | None:
    """Called by the Hermes plugin with the user's raw message. Returns the approved id, if any."""
    if not _YES.match(message or ""):
        return None
    with psycopg.connect(config.DB_DSN) as conn:
        row = conn.execute(
            """UPDATE pending_actions SET approved_at = now()
               WHERE id = (SELECT id FROM pending_actions
                           WHERE approved_at IS NULL AND executed_at IS NULL AND result IS NULL
                             AND created_at > now() - make_interval(mins => %s)
                           ORDER BY id DESC LIMIT 1)
               RETURNING id""",
            (config.PENDING_APPROVAL_MINUTES,),
        ).fetchone()
    return row[0] if row else None


def take_approved(action_id: int, kind: str) -> dict:
    """Claim an approved, not-yet-run action. Raises if the user has not approved it."""
    with psycopg.connect(config.DB_DSN, row_factory=dict_row) as conn:
        row = conn.execute(
            """UPDATE pending_actions SET executed_at = now()
               WHERE id = %s AND kind = %s AND approved_at IS NOT NULL AND executed_at IS NULL
               RETURNING payload, summary""",
            (action_id, kind),
        ).fetchone()
    if row is None:
        raise PermissionError(
            f"Action {action_id} is not approved. Show the user the proposal and wait for them to reply yes."
        )
    return row


def record_result(action_id: int, result: dict) -> None:
    with psycopg.connect(config.DB_DSN) as conn:
        conn.execute("UPDATE pending_actions SET result = %s WHERE id = %s", (json.dumps(result), action_id))

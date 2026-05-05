"""
SQLite persistence layer for DACRO negotiation decisions.
Every completed negotiation cycle is logged here for audit and frontend history replay.
"""

import dataclasses
import json
import logging
import sqlite3
from typing import Any, Dict, List, Optional

import config
from messaging.message_types import NegotiationDecision

logger = logging.getLogger(__name__)


class DecisionLog:
    """Wraps a SQLite database for persisting and querying negotiation decisions."""

    def __init__(self, db_path: str = config.SQLITE_DB_PATH) -> None:
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS negotiations (
                decision_id   TEXT PRIMARY KEY,
                event_id      TEXT,
                rfp_json      TEXT,
                award_json    TEXT,
                zone_states_json TEXT,
                gini_before   REAL,
                gini_after    REAL,
                xai_explanation TEXT,
                timestamp     TEXT
            )
        """)
        self._conn.commit()
        logger.info("DecisionLog initialized at %s", self._db_path)

    def log_decision(self, decision: NegotiationDecision) -> None:
        """Insert a negotiation decision record into SQLite."""
        rfp_json = json.dumps(dataclasses.asdict(decision.rfp)) if decision.rfp else "{}"
        award_json = (
            json.dumps(dataclasses.asdict(decision.award)) if decision.award else "{}"
        )
        zone_states_json = json.dumps(
            [dataclasses.asdict(z) if dataclasses.is_dataclass(z) else z
             for z in decision.zone_states]
        )
        try:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO negotiations
                    (decision_id, event_id, rfp_json, award_json, zone_states_json,
                     gini_before, gini_after, xai_explanation, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.decision_id,
                    decision.event_id,
                    rfp_json,
                    award_json,
                    zone_states_json,
                    decision.gini_before,
                    decision.gini_after,
                    decision.xai_explanation,
                    decision.timestamp,
                ),
            )
            self._conn.commit()
        except Exception as exc:
            logger.error("DecisionLog insert failed: %s", exc)

    def get_decisions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the last N decisions as a list of dicts, newest first."""
        cursor = self._conn.execute(
            "SELECT * FROM negotiations ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
        rows = cursor.fetchall()
        return [_row_to_dict(row) for row in rows]

    def get_decision(self, decision_id: str) -> Optional[Dict[str, Any]]:
        """Return a single decision by ID, or None if not found."""
        cursor = self._conn.execute(
            "SELECT * FROM negotiations WHERE decision_id = ?", (decision_id,)
        )
        row = cursor.fetchone()
        return _row_to_dict(row) if row else None

    def update_xai_explanation(self, decision_id: str, explanation: str) -> None:
        """Patch the XAI explanation into an existing decision record."""
        try:
            self._conn.execute(
                "UPDATE negotiations SET xai_explanation = ? WHERE decision_id = ?",
                (explanation, decision_id),
            )
            self._conn.commit()
        except Exception as exc:
            logger.error("DecisionLog update_xai failed: %s", exc)

    def close(self) -> None:
        if self._conn:
            self._conn.close()


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    for key in ("rfp_json", "award_json", "zone_states_json"):
        if d.get(key):
            try:
                d[key] = json.loads(d[key])
            except json.JSONDecodeError:
                pass
    return d

"""SQLite-based simulation trace -- logs all agent actions."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional


class SimulationTrace:
    """SQLite-based simulation trace -- logs all agent actions.

    Schema:
      steps(step_id, timestamp, active_count)
      actions(step_id, agent_id, cluster_id, vote, influence)
      snapshots(step_id, cluster_id, support_count, oppose_count, neutral_count)
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or ":memory:"
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        """Create tables."""
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS steps (
                step_id   INTEGER PRIMARY KEY,
                timestamp TEXT    NOT NULL,
                active_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS actions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                step_id    INTEGER NOT NULL,
                agent_id   TEXT    NOT NULL,
                cluster_id INTEGER NOT NULL,
                vote       TEXT    NOT NULL,
                influence  REAL    NOT NULL DEFAULT 1.0,
                FOREIGN KEY (step_id) REFERENCES steps(step_id)
            );

            CREATE TABLE IF NOT EXISTS snapshots (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                step_id       INTEGER NOT NULL,
                cluster_id    INTEGER NOT NULL,
                support_count INTEGER NOT NULL DEFAULT 0,
                oppose_count  INTEGER NOT NULL DEFAULT 0,
                neutral_count INTEGER NOT NULL DEFAULT 0,
                abstain_count INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (step_id) REFERENCES steps(step_id)
            );

            CREATE INDEX IF NOT EXISTS idx_actions_step ON actions(step_id);
            CREATE INDEX IF NOT EXISTS idx_snapshots_step ON snapshots(step_id);
            """
        )
        self._conn.commit()

    def log_step(self, step_id: int, results: List[Dict]) -> None:
        """Log one simulation step with all agent actions."""
        if self._conn is None:
            return

        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO steps (step_id, timestamp, active_count) VALUES (?, ?, ?)",
            (step_id, now, len(results)),
        )

        # Insert actions
        action_rows = [
            (step_id, r["agent_id"], r["cluster_id"], r["vote"], r["influence"])
            for r in results
        ]
        self._conn.executemany(
            "INSERT INTO actions (step_id, agent_id, cluster_id, vote, influence) "
            "VALUES (?, ?, ?, ?, ?)",
            action_rows,
        )

        # Build per-cluster snapshots
        cluster_votes: Dict[int, Dict[str, int]] = {}
        for r in results:
            cid = r["cluster_id"]
            vote = r["vote"]
            if cid not in cluster_votes:
                cluster_votes[cid] = {
                    "support": 0,
                    "oppose": 0,
                    "neutral": 0,
                    "abstain": 0,
                }
            if vote in cluster_votes[cid]:
                cluster_votes[cid][vote] += 1

        snapshot_rows = [
            (
                step_id,
                cid,
                counts["support"],
                counts["oppose"],
                counts["neutral"],
                counts["abstain"],
            )
            for cid, counts in cluster_votes.items()
        ]
        self._conn.executemany(
            "INSERT INTO snapshots "
            "(step_id, cluster_id, support_count, oppose_count, neutral_count, abstain_count) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            snapshot_rows,
        )

        self._conn.commit()

    def get_vote_distribution(self) -> Dict[int, Dict[str, int]]:
        """Get vote counts per cluster across all steps."""
        if self._conn is None:
            return {}

        cursor = self._conn.execute(
            "SELECT cluster_id, vote, COUNT(*) as cnt "
            "FROM actions GROUP BY cluster_id, vote"
        )
        result: Dict[int, Dict[str, int]] = {}
        for row in cursor.fetchall():
            cid, vote, cnt = row
            if cid not in result:
                result[cid] = {"support": 0, "oppose": 0, "neutral": 0, "abstain": 0}
            result[cid][vote] = cnt
        return result

    def get_timeline(self) -> List[Dict]:
        """Get step-by-step timeline of vote distributions."""
        if self._conn is None:
            return []

        cursor = self._conn.execute(
            "SELECT s.step_id, s.timestamp, s.active_count, "
            "sn.cluster_id, sn.support_count, sn.oppose_count, "
            "sn.neutral_count, sn.abstain_count "
            "FROM steps s LEFT JOIN snapshots sn ON s.step_id = sn.step_id "
            "ORDER BY s.step_id"
        )
        timeline: Dict[int, Dict] = {}
        for row in cursor.fetchall():
            step_id = row[0]
            if step_id not in timeline:
                timeline[step_id] = {
                    "step": step_id,
                    "timestamp": row[1],
                    "active_count": row[2],
                    "clusters": {},
                }
            if row[3] is not None:
                timeline[step_id]["clusters"][row[3]] = {
                    "support": row[4],
                    "oppose": row[5],
                    "neutral": row[6],
                    "abstain": row[7],
                }
        return list(timeline.values())

    def get_final_distribution(self) -> Dict[int, Dict[str, float]]:
        """Get final normalized vote distribution per cluster.

        Returns proportions (0.0-1.0) rather than raw counts.
        """
        raw = self.get_vote_distribution()
        result: Dict[int, Dict[str, float]] = {}
        for cid, votes in raw.items():
            total = sum(v for k, v in votes.items() if k != "abstain")
            if total == 0:
                result[cid] = {"support": 0.0, "oppose": 0.0, "neutral": 0.0}
            else:
                result[cid] = {
                    "support": votes.get("support", 0) / total,
                    "oppose": votes.get("oppose", 0) / total,
                    "neutral": votes.get("neutral", 0) / total,
                }
        return result

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

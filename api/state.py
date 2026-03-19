"""Shared global state: active_debates, metrics, constants."""

import time
from typing import Dict


# Global debate sessions store
active_debates: Dict[str, "DebateSession"] = {}


class SimpleMetrics:
    def __init__(self) -> None:
        self.total_debates: int = 0
        self.total_requests: int = 0
        self.total_errors: int = 0
        self.start_time: float = time.time()
        self.active_connections: int = 0

    def record_request(self) -> None:
        self.total_requests += 1

    def record_error(self) -> None:
        self.total_errors += 1

    def record_debate_start(self) -> None:
        self.total_debates += 1

    def record_connection_change(self, change: int) -> None:
        self.active_connections += change

    def get_stats(self) -> dict:
        uptime = time.time() - self.start_time
        return {
            "total_debates": self.total_debates,
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "active_connections": self.active_connections,
            "active_debates": len(active_debates),
            "uptime_seconds": uptime,
            "error_rate": self.total_errors / max(self.total_requests, 1),
        }


metrics = SimpleMetrics()

# Debate format definitions
DEBATE_FORMATS = {
    "adversarial": {
        "name": "대립형 토론 (MAD)",
        "support_team": "천사팀",
        "oppose_team": "악마팀",
        "organizer": {"name": "진행자", "role": "organizer", "emoji": "🎯"},
        "agents": {
            "support": [
                {"name": "희망천사", "role": "angel", "emoji": "😇"},
                {"name": "긍정작가", "role": "writer", "emoji": "✍️"},
            ],
            "oppose": [
                {"name": "도전악마", "role": "devil", "emoji": "😈"},
                {"name": "비판분석가", "role": "analyzer", "emoji": "🔍"},
            ],
        },
    },
    "collaborative": {
        "name": "협력형 토론",
        "support_team": "찬성 연구팀",
        "oppose_team": "반대 연구팀",
        "organizer": {"name": "연구진행자", "role": "organizer", "emoji": "🎯"},
        "agents": {
            "support": [
                {"name": "찬성연구원", "role": "searcher", "emoji": "🔎"},
                {"name": "찬성작가", "role": "writer", "emoji": "📝"},
            ],
            "oppose": [
                {"name": "반대연구원", "role": "searcher", "emoji": "🔍"},
                {"name": "반대작가", "role": "writer", "emoji": "✏️"},
            ],
        },
    },
    "competitive": {
        "name": "경쟁형 토론",
        "support_team": "블루팀",
        "oppose_team": "레드팀",
        "organizer": {"name": "심판", "role": "organizer", "emoji": "🎯"},
        "agents": {
            "support": [
                {"name": "블루탐색자", "role": "searcher", "emoji": "🔵"},
                {"name": "블루전략가", "role": "writer", "emoji": "💙"},
            ],
            "oppose": [
                {"name": "레드탐색자", "role": "searcher", "emoji": "🔴"},
                {"name": "레드전략가", "role": "writer", "emoji": "❤️"},
            ],
        },
    },
    "custom": {
        "name": "커스텀 토론",
        "support_team": "커스텀 A팀",
        "oppose_team": "커스텀 B팀",
        "organizer": {"name": "커스텀 진행자", "role": "organizer", "emoji": "🎯"},
        "agents": {
            "support": [],
            "oppose": [],
        },
        "custom": True,
    },
}

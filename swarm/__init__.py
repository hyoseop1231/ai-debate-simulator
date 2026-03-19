"""Swarm simulation engine -- rule-based agent swarm for debate opinion simulation."""

from swarm.agent_graph import AgentGraph
from swarm.engine import DebateSimulation
from swarm.rule_agent import ENTITY_TYPE_DEFAULTS, RuleAgent
from swarm.trace import SimulationTrace

__all__ = [
    "AgentGraph",
    "DebateSimulation",
    "ENTITY_TYPE_DEFAULTS",
    "RuleAgent",
    "SimulationTrace",
]

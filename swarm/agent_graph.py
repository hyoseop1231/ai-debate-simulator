"""Agent relationship graph -- dict-based, no igraph/neo4j dependency."""

from __future__ import annotations

import random
from typing import Dict, List, Optional

from models.schemas import ClusterProfile
from swarm.rule_agent import (
    ENTITY_TYPE_DISTRIBUTION,
    RuleAgent,
)


class AgentGraph:
    """Agent relationship graph -- dict-based (no igraph/neo4j dependency).

    Creates agents proportional to cluster weights and connects
    them in a small-world network topology.
    """

    def __init__(self) -> None:
        self.agents: List[RuleAgent] = []
        self._agent_map: Dict[str, RuleAgent] = {}

    def create_from_clusters(
        self,
        clusters: List[ClusterProfile],
        scale: int = 100,
    ) -> None:
        """Create agents proportional to cluster sizes.

        Example with scale=100:
          Cluster A (35%) -> 35 agents
          Cluster B (45%) -> 45 agents
          Cluster C (20%) -> 20 agents

        Entity types distributed per ENTITY_TYPE_DISTRIBUTION.
        """
        self.agents.clear()
        self._agent_map.clear()

        if not clusters:
            return

        # Normalize weights in case they don't sum to 1
        total_weight = sum(c.weight for c in clusters)
        if total_weight <= 0:
            total_weight = len(clusters)
            normalized = {c.cluster_id: 1.0 / len(clusters) for c in clusters}
        else:
            normalized = {c.cluster_id: c.weight / total_weight for c in clusters}

        # Calculate agent counts per cluster, ensuring at least 1 per cluster
        agent_counts: Dict[int, int] = {}
        remaining = scale
        for cluster in clusters:
            count = max(1, round(normalized[cluster.cluster_id] * scale))
            agent_counts[cluster.cluster_id] = count
            remaining -= count

        # Distribute remainder to largest clusters
        if remaining > 0:
            sorted_clusters = sorted(clusters, key=lambda c: c.weight, reverse=True)
            for i in range(remaining):
                cid = sorted_clusters[i % len(sorted_clusters)].cluster_id
                agent_counts[cid] += 1
        elif remaining < 0:
            # Over-allocated: trim from smallest clusters (keep min 1)
            sorted_clusters = sorted(clusters, key=lambda c: c.weight)
            for cluster in sorted_clusters:
                if remaining >= 0:
                    break
                can_remove = agent_counts[cluster.cluster_id] - 1
                remove = min(can_remove, -remaining)
                agent_counts[cluster.cluster_id] -= remove
                remaining += remove

        # Build entity type list for distribution
        entity_types = list(ENTITY_TYPE_DISTRIBUTION.keys())
        entity_weights = list(ENTITY_TYPE_DISTRIBUTION.values())

        # Create agents
        for cluster in clusters:
            count = agent_counts[cluster.cluster_id]
            for idx in range(count):
                # Pick entity type by weighted distribution
                entity_type = random.choices(entity_types, weights=entity_weights, k=1)[0]
                agent = RuleAgent.create_for_cluster(cluster, idx, entity_type)
                self.agents.append(agent)
                self._agent_map[agent.agent_id] = agent

        # Build connections
        self._build_connections()

    def _build_connections(self) -> None:
        """Build small-world network connections.

        - Agents in same cluster: high connection probability (0.3)
        - Agents in different clusters: low connection probability (0.05)
        - Each agent gets 3-8 neighbors
        """
        if len(self.agents) <= 1:
            return

        # Group agents by cluster
        cluster_groups: Dict[int, List[RuleAgent]] = {}
        for agent in self.agents:
            cluster_groups.setdefault(agent.cluster_id, []).append(agent)

        for agent in self.agents:
            target_neighbors = random.randint(3, min(8, len(self.agents) - 1))
            candidates: List[RuleAgent] = []
            weights: List[float] = []

            for other in self.agents:
                if other.agent_id == agent.agent_id:
                    continue
                if other.agent_id in agent.neighbors:
                    continue

                if other.cluster_id == agent.cluster_id:
                    weights.append(0.3)
                else:
                    weights.append(0.05)
                candidates.append(other)

            if not candidates:
                continue

            # How many more neighbors needed
            need = max(0, target_neighbors - len(agent.neighbors))
            if need == 0:
                continue

            # Sample neighbors
            pick_count = min(need, len(candidates))
            chosen = random.choices(candidates, weights=weights, k=pick_count)

            # Deduplicate
            seen = set(agent.neighbors)
            for neighbor in chosen:
                if neighbor.agent_id not in seen:
                    agent.neighbors.append(neighbor.agent_id)
                    # Bidirectional connection
                    if agent.agent_id not in neighbor.neighbors:
                        neighbor.neighbors.append(agent.agent_id)
                    seen.add(neighbor.agent_id)

    def get(self, agent_id: str) -> Optional[RuleAgent]:
        """Get agent by ID."""
        return self._agent_map.get(agent_id)

    def get_neighbors(self, agent_id: str) -> List[RuleAgent]:
        """Get neighbor agents."""
        agent = self._agent_map.get(agent_id)
        if agent is None:
            return []
        return [
            self._agent_map[nid]
            for nid in agent.neighbors
            if nid in self._agent_map
        ]

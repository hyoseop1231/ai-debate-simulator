/**
 * OpenClaw AI Debate Simulator Extension
 *
 * Connects to the AI Debate Simulator API.
 *
 * Commands:
 *   /debate start --topic "..."  -> POST /api/forum/start
 *   /debate status               -> GET  /api/forum/{id}/status
 *   /debate result               -> GET  /api/forum/{id}/result
 */

const API_BASE = process.env.DEBATE_API_URL || "http://localhost:8003";

async function startDebate(topic) {
  const res = await fetch(`${API_BASE}/api/forum/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic }),
  });
  return res.json();
}

async function getStatus(sessionId) {
  const res = await fetch(`${API_BASE}/api/forum/${sessionId}/status`);
  return res.json();
}

async function getResult(sessionId) {
  const res = await fetch(`${API_BASE}/api/forum/${sessionId}/result`);
  return res.json();
}

module.exports = { startDebate, getStatus, getResult };

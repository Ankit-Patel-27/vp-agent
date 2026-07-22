"""
RAG Store — JSON-based trade memory.
Stores VP setups, outcomes. Used for context only — never overrides rules.
"""
import json, os, uuid
from datetime import datetime, timezone
from pathlib import Path


STORE_FILE = "rag_memory.json"


class RAGStore:
    def __init__(self, path: str = STORE_FILE):
        self.path = Path(path)
        self._data: list = self._load()

    def _load(self) -> list:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception:
                return []
        return []

    def _save(self):
        self.path.write_text(json.dumps(self._data, indent=2))

    def store(self, case: dict) -> str:
        case_id = str(uuid.uuid4())[:8]
        case["case_id"] = case_id
        case.setdefault("outcome", {"result": "pending"})
        self._data.append(case)
        self._save()
        return case_id

    def log_outcome(self, case_id: str, result: str,
                    exit_price: float, r_achieved: float, notes: str = "") -> bool:
        for c in self._data:
            if c.get("case_id") == case_id:
                c["outcome"] = {
                    "result":     result,
                    "exit_price": exit_price,
                    "r_achieved": r_achieved,
                    "notes":      notes,
                    "logged_at":  datetime.now(timezone.utc).isoformat(),
                }
                self._save()
                return True
        return False

    def find_similar(self, case: dict, n: int = 3) -> list:
        """Simple similarity: same setup_type + similar bias."""
        target_setup = case.get("setup_type", "none")
        target_bias  = case.get("trade_bias", "neutral")
        completed    = [c for c in self._data
                        if c.get("outcome", {}).get("result") not in ("pending", None)]
        scored = []
        for c in completed:
            s = 0
            if c.get("setup_type") == target_setup: s += 3
            if c.get("trade_bias") == target_bias:  s += 2
            if c.get("asset") == case.get("asset"): s += 1
            scored.append((s, c))
        scored.sort(key=lambda x: -x[0])
        return [c for _, c in scored[:n]]

    def context_text(self, cases: list) -> str:
        if not cases:
            return "No similar past cases found."
        lines = []
        for c in cases:
            o = c.get("outcome", {})
            lines.append(
                f"- {c.get('setup_type','?')} {c.get('trade_bias','?')} on {c.get('asset','?')}: "
                f"{o.get('result','pending')} "
                f"({o.get('r_achieved', 0)}R) | news:{c.get('news',{}).get('direction','?')}"
            )
        return "\n".join(lines)

    def all_cases(self) -> list:
        return list(reversed(self._data))

    def stats(self) -> dict:
        completed = [c for c in self._data
                     if c.get("outcome", {}).get("result") not in ("pending", None, "")]
        n = len(completed)
        wins   = [c for c in completed if c["outcome"]["result"] == "win"]
        losses = [c for c in completed if c["outcome"]["result"] == "loss"]
        wr     = round(len(wins) / n * 100, 1) if n else 0
        avg_r  = round(sum(c["outcome"].get("r_achieved", 0) for c in wins) / len(wins), 2) if wins else 0
        return {
            "total":    len(self._data),
            "completed": n,
            "wins":     len(wins),
            "losses":   len(losses),
            "win_rate": wr,
            "avg_r":    avg_r,
        }

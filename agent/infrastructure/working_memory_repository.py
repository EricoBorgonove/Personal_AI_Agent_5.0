import json
from agent.domain.working_memory import Draft


class WorkingMemoryRepository:
    """Shares the existing Unit of Work; never commits independently."""
    def __init__(self, db):
        self.db = db

    def load(self, sender, role):
        row = self.db.execute('''SELECT tool, slots, evidence FROM working_memory_v1
            WHERE sender=? AND role=? AND updated_at>=datetime('now','-7 days')''',
            (sender, role)).fetchone()
        return Draft(row[0], json.loads(row[1]), json.loads(row[2])) if row else None

    def save(self, sender, role, draft):
        self.db.execute("DELETE FROM working_memory_v1 WHERE updated_at<datetime('now','-7 days')")
        self.db.execute('''INSERT INTO working_memory_v1(sender,role,tool,slots,evidence)
            VALUES (?,?,?,?,?) ON CONFLICT(sender,role) DO UPDATE SET
            tool=excluded.tool, slots=excluded.slots, evidence=excluded.evidence,
            updated_at=CURRENT_TIMESTAMP''', (sender, role, draft.tool,
            json.dumps(draft.slots, ensure_ascii=False),
            json.dumps(draft.evidence, ensure_ascii=False)))

    def clear(self, sender, role):
        self.db.execute('DELETE FROM working_memory_v1 WHERE sender=? AND role=?', (sender, role))


# Name used by the standalone hotfix.
SQLiteDraftRepository = WorkingMemoryRepository

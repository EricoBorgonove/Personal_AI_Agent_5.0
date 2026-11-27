import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from agent.application.conversation import required_fields, resolve_args
from agent.application.dialogue import DialogueManager
from agent.application.working_memory import WorkingMemoryManager
from agent.domain.policies import TZ
from agent.domain.working_memory import Draft
from agent.infrastructure.sqlite import SQLiteUnitOfWork
from agent.infrastructure.working_memory_repository import SQLiteDraftRepository


class WorkingMemoryTests(unittest.TestCase):
    def setUp(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.uow = SQLiteUnitOfWork(Path(tmp) / 'test.db')
        self.today = datetime(2026, 11, 26, 13, tzinfo=TZ)
        self.dialogue = DialogueManager()

    def apply(self, state, transition='UPDATE_TASK', action='PERGUNTAR', tool='agenda_criar', **args):
        return self.dialogue.apply(state, {'context_action': transition, 'action': action,
                                          'tool': tool, 'args': args}, self.today)

    def memory(self, db, sender='owner', role='pessoal'):
        return WorkingMemoryManager(SQLiteDraftRepository(db), sender, role)

    def fill(self, state):
        self.apply(state, 'CREATE_TASK', titulo='Palestra')
        self.apply(state, dia_offset=1, hora='14:00')
        return self.apply(state, minutos=50)

    def test_palestra_multiturn(self):
        with self.uow.transaction() as db:
            state = self.memory(db)
            fields = self.fill(state)
            self.assertEqual(resolve_args('agenda_criar', fields, self.today),
                             {'titulo': 'Palestra', 'inicio': '2026-11-27 14:00', 'fim': '2026-11-27 14:50'})

    def test_restart_and_relative_date(self):
        with self.uow.transaction() as db:
            state = self.memory(db)
            self.fill(state)
            state.save()
        with self.uow.transaction() as db:
            self.today = self.today.replace(day=27)
            state = self.memory(db)
            fields = self.apply(state, minutos=120)
            self.assertEqual(resolve_args('agenda_criar', fields, self.today)['fim'], '2026-11-27 16:00')

    def test_permissions_and_isolation(self):
        with self.uow.transaction() as db:
            state = self.memory(db)
            self.fill(state)
            state.save()
            self.assertIsNone(self.memory(db, 'external', 'social').active)
            self.assertIsNone(self.memory(db, 'owner', 'social').active)
            self.assertIsNone(self.memory(db, 'other').active)

    def test_interrupt(self):
        with self.uow.transaction() as db:
            state = self.memory(db)
            fields = self.fill(state)
            task_id = state.active['id']
            self.apply(state, 'CREATE_TASK', tool='financeiro_registrar', valor='50,00')
            state.resume(task_id)
            self.assertEqual(state.active['fields'], fields)
            self.assertEqual(state.data['suspended'][0]['fields'], {'valor': '50,00'})

    def test_cancel_no_write(self):
        with self.uow.transaction() as db:
            state = self.memory(db)
            self.fill(state)
            self.apply(state, 'CANCEL_TASK', tool=None)
            self.assertIsNone(state.active)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM calendar_events').fetchone()[0], 0)

    def test_correction_invalidates_confirmation(self):
        with self.uow.transaction() as db:
            state = self.memory(db)
            fields = self.fill(state)
            state.active['preview'] = {'tool': 'agenda_criar', 'args': resolve_args('agenda_criar', fields, self.today)}
            self.apply(state, hora='10:00')
            self.assertNotIn('preview', state.active)
            self.assertEqual(state.active['fields']['minutos'], 50)

    def test_clear_hour_preserves_date_and_invalidates_preview(self):
        with self.uow.transaction() as db:
            state = self.memory(db)
            self.apply(state, 'CREATE_TASK', titulo='Palestra', inicio='2026-11-27T09:00:00', minutos=50)
            state.active['preview'] = {'tool': 'agenda_criar', 'args': {'inicio': '2026-11-27 09:00'}}
            fields = self.dialogue.apply(state, {
                'context_action': 'UPDATE_TASK', 'action': 'PERGUNTAR', 'tool': 'agenda_criar',
                'args': {}, 'clear_fields': ['hora'],
            }, self.today)
            self.assertEqual(fields, {'titulo': 'Palestra', 'data': '2026-11-27', 'minutos': 50})
            self.assertNotIn('preview', state.active)

    def test_expired(self):
        with self.uow.transaction() as db:
            state = self.memory(db)
            self.fill(state)
            state.save()
            db.execute("UPDATE working_memory_v1 SET updated_at=datetime('now','-8 days')")
            self.assertIsNone(self.memory(db).active)

    def test_incomplete_fields_and_invalid_duration(self):
        with self.uow.transaction() as db:
            state = self.memory(db)
            fields = self.apply(state, 'CREATE_TASK', titulo='Palestra', dia_offset=1)
            tools = {'agenda_criar': '{"titulo":"...","inicio":"...","fim":"..."}'}
            self.assertEqual(required_fields('agenda_criar', tools, fields), ['hora', 'minutos'])
            with self.assertRaises(ValueError):
                self.apply(state, hora='09:00', minutos=-1)
            self.assertEqual(state.active['fields'], fields)

    def test_legacy_draft_requires_explicit_resume(self):
        with self.uow.transaction() as db:
            store = SQLiteDraftRepository(db)
            store.save('owner', 'pessoal', Draft('agenda_criar', {'titulo': 'Palestra antiga'}))
            state = self.memory(db)
            self.assertIsNone(state.active)
            state.resume(state.data['suspended'][0]['id'])
            self.assertEqual(state.active['fields'], {'titulo': 'Palestra antiga'})


if __name__ == '__main__':
    unittest.main()

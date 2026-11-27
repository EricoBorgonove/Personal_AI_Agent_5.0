import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from agent.application.working_memory import WorkingMemoryManager
from agent.infrastructure.working_memory_repository import SQLiteDraftRepository
from agent.infrastructure.sqlite import SQLiteUnitOfWork


class WorkingMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'test.db'
        SQLiteUnitOfWork(self.path)
        self.today = date(2026, 11, 26)
        self.open()

    def open(self):
        self.db = sqlite3.connect(self.path)
        self.store = SQLiteDraftRepository(self.db)
        self.manager = WorkingMemoryManager(self.store)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def send(self, text, sender='owner', role='pessoal', authorized=True):
        return self.manager.route(sender, role, authorized, text, self.today)

    def fill(self):
        self.send('Guarde na minha agenda uma palestra')
        self.send('Amanhã às 14h')
        return self.send('50 minutos')

    def test_palestra_multiturn(self):
        self.assertIn('data', self.send('Guarde na minha agenda uma palestra').reply)
        self.assertIn('duração', self.send('Amanhã às 14h').reply)
        self.assertIn('14:50', self.send('50 minutos').reply)
        plan = self.send('Confirmo o compromisso')
        self.assertEqual(plan.tool,'agenda_criar')
        self.assertEqual(plan.args, {'titulo':'palestra','inicio':'2026-11-27 14:00','fim':'2026-11-27 14:50'})
        self.manager.complete('owner','pessoal')
        self.assertIsNone(self.send('Confirmo o compromisso'))

    def test_restart_and_relative_date(self):
        self.send('Agende uma palestra sobre IA')
        self.send('Amanhã')
        self.db.commit(); self.db.close(); self.open()
        self.today = date(2026,11,27)
        self.send('14h'); self.send('duas horas')
        plan = self.send('Confirmo o compromisso')
        self.assertEqual(plan.args['inicio'],'2026-11-27 14:00')
        self.assertEqual(plan.args['fim'],'2026-11-27 16:00')
        self.assertEqual(plan.args['titulo'],'palestra sobre IA')

    def test_permissions_and_isolation(self):
        self.fill()
        self.assertIsNone(self.send('/contexto',sender='external',role='social',authorized=False))
        self.assertIsNone(self.send('Confirmo o compromisso',sender='external',role='social',authorized=False))
        self.assertIsNone(self.send('Confirmo o compromisso',sender='owner',role='social',authorized=False))
        self.assertIn('Não há',self.send('/contexto',sender='other').reply)

    def test_interrupt(self):
        self.send('Agende uma palestra')
        self.assertIsNone(self.send('Quanto gastei este mês?'))
        self.assertIn('palestra',self.send('/contexto').reply)
        self.send('Amanhã'); self.send('14h'); self.send('duas horas')
        self.assertEqual(self.send('Confirmo o compromisso').args['fim'],'2026-11-27 16:00')

    def test_cancel_no_write(self):
        self.fill()
        self.assertIn('encerrado',self.send('/cancelar').reply)
        self.assertIsNone(self.send('Confirmo o compromisso'))

    def test_requires_confirmation(self):
        self.assertIsNone(self.fill().tool)
        self.assertIsNone(self.send('sim').tool)
        self.assertIsNone(self.send('Não confirme').tool)
        self.assertEqual(self.send('Confirmo o compromisso').tool,'agenda_criar')

    def test_expired(self):
        self.fill()
        self.db.execute("UPDATE working_memory_v1 SET updated_at=datetime('now','-8 days')")
        self.assertIn('Não há',self.send('/contexto').reply)
        self.assertIsNone(self.send('Confirmo o compromisso'))

    def test_ambiguous_and_incomplete(self):
        self.send('Agende uma palestra')
        self.send('Amanhã ou hoje')
        self.assertIn('data',self.send('/contexto').reply)
        self.assertIsNone(self.send('Confirmo o compromisso').tool)
        self.send('Amanhã às 25h')
        self.assertIn('horário de início',self.send('/contexto').reply)

    def test_preserve_existing_advanced_route(self):
        self.assertIsNone(self.send('Agende uma aula amanhã das 14h às 15h'))
        self.assertIsNone(self.send('Agende uma aula semanal'))


if __name__ == '__main__':
    unittest.main()

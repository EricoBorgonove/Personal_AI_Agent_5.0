import tempfile,unittest
from pathlib import Path
from datetime import timedelta
from agent.bootstrap import build_app
from agent.infrastructure.repositories import Repository
from agent.application.specialists.calendar import CalendarService
from agent.application.tools import build_registry
from agent.application.executor import Executor
from agent.application.meetings import MeetingService
from agent.application.calendar_reminders import CalendarReminderService
from agent.interfaces.calendar_export import export
from agent.domain.policies import now
from agent.domain.calendar import FMT

class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/'test.db'); self.app=build_app(self.path,'owner')
        self.start=(now()+timedelta(days=2)).replace(hour=10,minute=0,second=0,microsecond=0)
    def slot(self,h=0): return (self.start+timedelta(hours=h)).strftime(FMT)
    def test_overlap_and_free(self):
        with self.app.uow.transaction() as d:
            s=CalendarService(Repository(d).calendar); i=s.create('A',self.slot(),self.slot(2))
            with self.assertRaises(ValueError): s.create('B',self.slot(1),self.slot(3))
            s.create('C',self.slot(2),self.slot(3)); self.assertEqual(s.free(self.slot(-1),self.slot(4),60),[{'inicio':self.slot(-1),'fim':self.slot()},{'inicio':self.slot(3),'fim':self.slot(4)}]); s.change(i,self.slot(4),self.slot(5)); s.cancel(i)
    def test_meeting_and_privacy(self):
        with self.app.uow.transaction() as d:
            r=Repository(d); s=CalendarService(r.calendar); s.create('Privado',self.slot(),self.slot(2)); m=MeetingService(r,'owner'); i=m.create('aluno','João','TCC',self.slot(1))['id']; self.assertIn('conflito',m.decision('owner',f'Confirmo a reunião #{i}')); self.assertEqual(r.request(i)['status'],'PENDENTE'); m.decision('owner',f'Proponho #{i} {self.slot(3)}'); m.decision('aluno',f'Aceito a reunião #{i}'); m.decision('owner',f'Confirmo a reunião #{i}'); self.assertEqual(len(s.list(self.slot(3),self.slot(4))),1)
            e=Executor(build_registry(r,'owner',self.app.knowledge),self.app.factory)
            with self.assertRaises(ValueError): e.execute('aluno','agenda_listar',{'inicio':self.slot(),'fim':self.slot(5)})
    def test_recurrence_export_reminders(self):
        with self.app.uow.transaction() as d:
            r=Repository(d); s=CalendarService(r.calendar); ids=s.recurring('Aula; prática',self.slot(),self.slot(1),'aula','alta','semanal',3); self.assertEqual(len(ids),3)
            with self.assertRaises(ValueError): s.recurring('B',self.slot(),self.slot(1),'aula','normal','semanal',2)
            reminders=CalendarReminderService(r,'owner'); self.assertGreater(reminders.enqueue(self.start-timedelta(minutes=15)),0); self.assertEqual(reminders.enqueue(self.start-timedelta(minutes=15)),0)
            self.assertTrue(all(x['recipient']=='owner' for x in r.pending()))
        path = Path(self.tmp.name) / 'test.ics'

        self.assertEqual(export(self.path, path), 3)

        content = path.read_text(encoding="utf-8")

        self.assertIn('SUMMARY:Aula\\; prática', content)
        self.assertIn('DTSTART:', content)

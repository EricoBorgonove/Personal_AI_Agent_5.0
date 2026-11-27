import tempfile,unittest
from pathlib import Path
from datetime import date,timedelta
from agent.bootstrap import build_app
from agent.application.executor import Executor
from agent.application.tools import build_registry
from agent.infrastructure.repositories import Repository
from agent.domain.policies import now
from agent.domain.obligations import split_amount,shift_month
from agent.application.reminders import FinanceReminderService

class ObligationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.app=build_app(str(Path(self.tmp.name)/'db'),'owner')
    def test_installment_math(self):
        self.assertEqual(split_amount(10000,3),[3334,3333,3333])
        self.assertEqual(shift_month('2028-01-31',1),'2028-02-29')
        self.assertEqual(shift_month('2028-01-31',2),'2028-03-31')
    def test_cards_and_settlement(self):
        with self.app.uow.transaction() as db:
            repo=Repository(db); e=Executor(build_registry(repo,'owner',self.app.knowledge),self.app.factory)
            run=lambda name,args:e.execute('owner','financeiro_'+name,args)
            card=run('cartao',{'nome':'Teste','limite':'100','fechamento':20,'vencimento':31})['id']
            args={'cartao_id':card,'descricao':'Livro','categoria':'educacao','valor_total':'100','parcelas':3,'primeiro_vencimento':'2028-02-29'}
            purchase=run('compra_parcelada',args); self.assertEqual([r['vencimento'] for r in purchase['parcelas']],['2028-02-29','2028-03-31','2028-04-30'])
            self.assertEqual(run('cartoes',{})[0]['disponivel_brl'],'0.00')
            with self.assertRaises(ValueError): run('compra_parcelada',args)
            for tool in ('financeiro_cartoes','financeiro_contas','financeiro_vencimentos','financeiro_criar_conta'):
                with self.assertRaises(ValueError): e.execute('aluno',tool,{})
            self.assertEqual(run('resumo',{'mes':'2028-02'})['despesas_brl'],'0.00')
        i=purchase['parcelas'][0]['id']; self.app.handle('owner',f'Liquido a conta #{i}'); self.app.handle('owner',f'Liquido a conta #{i}')
        with self.app.uow.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM finance_entries').fetchone()[0],1)
            repo=Repository(db); self.assertEqual(repo.obligations.get(i)['status'],'liquidado'); self.assertEqual(repo.finance.void(1),0)
            self.assertEqual(repo.obligations.cards()[0]['committed'],6666)
    def test_recurrence_and_reminders(self):
        with self.app.uow.transaction() as db:
            repo=Repository(db); e=Executor(build_registry(repo,'owner',self.app.knowledge),self.app.factory)
            today=now().date(); a={'tipo':'despesa','descricao':'Internet','categoria':'moradia','valor':'120','vencimento':today.isoformat(),'meses':3}
            ids=e.execute('owner','financeiro_recorrencia',a)['contas']; self.assertEqual(len(ids),3)
            r=FinanceReminderService(repo,'owner'); self.assertEqual(r.enqueue(today),1); self.assertEqual(r.enqueue(today),0)
            self.assertEqual(len(repo.pending()),1); self.assertEqual(repo.pending()[0]['recipient'],'owner')
        self.app.handle('owner',f'Cancelo a conta #{ids[0]}')
        with self.app.uow.connection() as db:
            self.assertEqual(Repository(db).obligations.get(ids[0])['status'],'cancelado')

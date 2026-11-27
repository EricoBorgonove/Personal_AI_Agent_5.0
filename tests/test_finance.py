import tempfile,unittest
from pathlib import Path
from agent.bootstrap import build_app
from agent.application.executor import Executor
from agent.application.tools import build_registry
from agent.infrastructure.repositories import Repository

class FinanceTests(unittest.TestCase):
    def test_finance(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=build_app(str(Path(tmp)/'db'),'owner')
            with app.uow.transaction() as db:
                e=Executor(build_registry(Repository(db),'owner',app.knowledge),app.factory)
                def run(tool,args): return e.execute('owner',tool,args)
                args={'tipo':'despesa','valor':'35,90','categoria':'alimentacao','descricao':'almoço','data':'2026-11-26'}
                run('financeiro_registrar',args)
                run('financeiro_registrar',{**args,'tipo':'receita','valor':'100,00','categoria':'salario'})
                run('financeiro_orcamento',{'mes':'2026-11','categoria':'alimentacao','valor':'50'})
                report=run('financeiro_resumo',{'mes':'2026-11'})
                self.assertEqual(report['saldo_do_mes_brl'],'64.10')
                self.assertEqual(report['orcamentos'][0]['restante_brl'],'14.10')
                with self.assertRaises(ValueError): e.execute('aluno','financeiro_extrato',{})
                with self.assertRaises(ValueError): run('financeiro_registrar',{**args,'valor':'-1'})
            app.handle('owner','Estorno o lançamento #1')
            with app.uow.connection() as db:
                self.assertEqual(db.execute('SELECT voided FROM finance_entries WHERE id=1').fetchone()[0],1)

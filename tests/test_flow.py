import unittest,tempfile
from pathlib import Path
from datetime import timedelta
from agent.bootstrap import build_app
from agent.application.executor import Executor
from agent.application.tools import build_registry
from agent.infrastructure.repositories import Repository
from agent.domain.policies import now
class Test(unittest.TestCase):
 def test_flow(self):
    with tempfile.TemporaryDirectory() as t:
      slot=(now()+timedelta(days=1)).strftime('%Y-%m-%d %H:%M'); slot2=(now()+timedelta(days=2)).strftime('%Y-%m-%d %H:%M')
      def model(*_):
        self.fail('O pedido de reunião completo deve dispensar o modelo')
      pedido=f'Solicito reunião. Nome: João. Assunto: TCC. Data: {slot}.'
      a=build_app(str(Path(t)/'test.db'),'owner',model); a.handle('aluno',pedido, '1'); a.handle('aluno',pedido,'1')
      a.handle('intruso','Confirmo a reunião #1'); a.handle('aluno','Confirmo a reunião #1'); a.handle('owner',f'Proponho #1 {slot2}'); a.handle('aluno','Aceito a reunião #1'); a.handle('owner','Confirmo a reunião #1')
      with a.uow.connection() as d:
        self.assertEqual(d.execute('SELECT count(*) FROM requests').fetchone()[0],1); self.assertEqual(d.execute('SELECT status FROM requests').fetchone()[0],'CONFIRMADA'); repo=Repository(d); e=Executor(build_registry(repo,'owner',a.knowledge),a.factory); self.assertEqual(e.execute('intruso','solicitacoes',{}),[])
        with self.assertRaises(ValueError): e.execute('aluno','memorias',{})
      sent=[]; a.flush(lambda to,msg: sent.append((to,msg))); self.assertTrue(any(to=='aluno' and 'confirmada pelo' in msg for to,msg in sent)); a.flush(lambda *x:self.fail('Duplicação de envio'))
if __name__=='__main__': unittest.main()

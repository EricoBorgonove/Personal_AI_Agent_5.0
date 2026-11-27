import json
import tempfile
import unittest
from pathlib import Path

from agent.bootstrap import build_app


class TurnBudgetTests(unittest.TestCase):
    def run_turn(self, budget):
        queries = iter(['tarefas', 'recados', 'memorias', 'solicitacoes'])
        calls = []

        def model(messages, schema):
            calls.append(1)
            tool = next(queries, None)
            if tool is None:
                return json.dumps({'action': 'RESPONDER', 'message': 'Pronto.'})
            return json.dumps({'action': 'EXECUTAR', 'tool': tool, 'args': {'busca': 'x'} if tool == 'memorias' else {}})

        with tempfile.TemporaryDirectory() as directory:
            app = build_app(Path(directory) / 'agent.db', 'owner', model, turn_budget=budget)
            app.handle('owner', 'Mostre tudo o que está pendente.')
            replies = []
            app.flush(lambda _, reply: replies.append(reply))
        return len(calls), replies

    def test_exhausted_budget_answers_with_results_so_far(self):
        calls, replies = self.run_turn(0)
        self.assertEqual(calls, 1)
        self.assertIn('As demais etapas ficaram pendentes', replies[0])

    def test_budget_allows_replanning_while_time_remains(self):
        calls, _ = self.run_turn(90)
        self.assertGreater(calls, 1)

    def test_invalid_budget_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            build_app(Path(directory) / 'agent.db', 'owner', lambda *_: '{}', turn_budget=-1)


if __name__ == '__main__':
    unittest.main()

import json
import os
import unittest
from unittest.mock import patch

from agent.infrastructure import ollama

REPLY = {'done': True, 'done_reason': 'stop', 'message': {'content': '{}'}}


class OllamaUsageTests(unittest.TestCase):
    def call(self, env, reply):
        sent = []

        def fake_post(path, payload):
            sent.append(payload)
            return reply

        with patch.dict(os.environ, env, clear=False), patch.object(ollama, 'post_ollama', fake_post), \
                self.assertLogs('agent.infrastructure.ollama', 'INFO') as logs:
            ollama.ask_ollama([{'role': 'user', 'content': 'oi'}])
        return sent[0], '\n'.join(logs.output)

    def test_context_options_come_from_environment(self):
        payload, logs = self.call({'OLLAMA_NUM_CTX': '8192', 'OLLAMA_NUM_PREDICT': '400', 'OLLAMA_MODEL': 'qwen3:8b'},
                                  {**REPLY, 'prompt_eval_count': 2214, 'eval_count': 40})
        self.assertEqual((payload['options']['num_ctx'], payload['options']['num_predict']), (8192, 400))
        self.assertIn('tokens modelo=qwen3:8b prompt=2214 resposta=40 contexto=8192', logs)
        self.assertNotIn('WARNING', logs)

    def test_warns_when_prompt_leaves_no_room_for_the_answer(self):
        _, logs = self.call({'OLLAMA_NUM_CTX': '4096', 'OLLAMA_NUM_PREDICT': '320'},
                            {**REPLY, 'prompt_eval_count': 3900})
        self.assertIn('contexto_esgotado prompt=3900', logs)

    def test_warns_near_the_limit(self):
        _, logs = self.call({'OLLAMA_NUM_CTX': '4096', 'OLLAMA_NUM_PREDICT': '320'},
                            {**REPLY, 'prompt_eval_count': 3600})
        self.assertIn('contexto_proximo_do_limite prompt=3600', logs)

    def test_invalid_setting_is_rejected(self):
        with patch.dict(os.environ, {'OLLAMA_NUM_CTX': '0'}), self.assertRaises(ValueError):
            ollama.ask_ollama([])


if __name__ == '__main__':
    unittest.main()

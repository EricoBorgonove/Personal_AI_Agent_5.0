import json
import logging
import os
import urllib.request
from urllib.error import HTTPError

logger = logging.getLogger(__name__)
DEFAULT_MODEL = 'qwen2.5:3b'
# Warn while there is still room: tool results and retries grow the prompt within a turn.
CONTEXT_WARNING_RATIO = 0.85


class OllamaHTTPError(RuntimeError):
    def __init__(self, status):
        self.http_status = status
        super().__init__(f'Ollama retornou HTTP {status}')


def _int_env(name, default):
    value = os.getenv(name, '').strip()
    if not value:
        return default
    number = int(value)
    if number <= 0:
        raise ValueError(f'{name} deve ser um inteiro positivo.')
    return number


def model_name():
    return os.getenv('OLLAMA_MODEL', DEFAULT_MODEL)


def post_ollama(path, payload):
    url = os.getenv('OLLAMA_URL', 'http://localhost:11434').rstrip('/') + path
    request = urllib.request.Request(
        url, json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        {'Content-Type': 'application/json; charset=utf-8'},
    )
    try:
        with urllib.request.urlopen(request, timeout=_int_env('OLLAMA_TIMEOUT', 120)) as response:
            data = json.loads(response.read().decode('utf-8-sig'))
    except HTTPError as error:
        error.close()
        raise OllamaHTTPError(error.code) from error
    if not isinstance(data, dict) or 'error' in data:
        raise ValueError('Envelope inválido do Ollama')
    return data


def log_usage(data, model, num_ctx, num_predict):
    prompt, output = data.get('prompt_eval_count'), data.get('eval_count')
    if not isinstance(prompt, int):
        return
    logger.info('[LLM] tokens modelo=%s prompt=%d resposta=%s contexto=%d', model, prompt, output, num_ctx)
    if prompt + num_predict >= num_ctx:
        logger.warning('[LLM] contexto_esgotado prompt=%d reserva_resposta=%d contexto=%d '
                       '(o Ollama descarta o início do prompt; aumente OLLAMA_NUM_CTX)',
                       prompt, num_predict, num_ctx)
    elif prompt >= num_ctx * CONTEXT_WARNING_RATIO:
        logger.warning('[LLM] contexto_proximo_do_limite prompt=%d contexto=%d', prompt, num_ctx)


def ask_ollama(messages, schema=None):
    num_ctx, num_predict = _int_env('OLLAMA_NUM_CTX', 4096), _int_env('OLLAMA_NUM_PREDICT', 320)
    payload = {'model': model_name(), 'messages': messages, 'stream': False, 'think': False,
               'options': {'temperature': 0, 'num_ctx': num_ctx, 'num_predict': num_predict}}
    if schema is not None:
        payload['format'] = schema
    data = post_ollama('/api/chat', payload)
    log_usage(data, payload['model'], num_ctx, num_predict)
    if data.get('done_reason') == 'length':
        raise ValueError('Resposta truncada do Ollama')
    if data.get('done') is not True:
        raise ValueError('Resposta incompleta do Ollama')
    message = data.get('message')
    content = message.get('content') if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError('Conteúdo vazio ou inválido do Ollama')
    return content

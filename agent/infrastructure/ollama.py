import json
import os
import urllib.request
from urllib.error import HTTPError


class OllamaHTTPError(RuntimeError):
    def __init__(self, status):
        self.http_status = status
        super().__init__(f'Ollama retornou HTTP {status}')


def post_ollama(path, payload):
    url = os.getenv('OLLAMA_URL', 'http://localhost:11434').rstrip('/') + path
    request = urllib.request.Request(
        url, json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        {'Content-Type': 'application/json; charset=utf-8'},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode('utf-8-sig'))
    except HTTPError as error:
        error.close()
        raise OllamaHTTPError(error.code) from error
    if not isinstance(data, dict) or 'error' in data:
        raise ValueError('Envelope inválido do Ollama')
    return data


def ask_ollama(messages, schema=None):
    payload = {'model': os.getenv('OLLAMA_MODEL', 'qwen2.5:3b'), 'messages': messages,
               'stream': False, 'options': {'temperature': 0}}
    if schema is not None:
        payload['format'] = schema
    data = post_ollama('/api/chat', payload)
    if data.get('done_reason') == 'length':
        raise ValueError('Resposta truncada do Ollama')
    if data.get('done') is not True:
        raise ValueError('Resposta incompleta do Ollama')
    message = data.get('message')
    content = message.get('content') if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError('Conteúdo vazio ou inválido do Ollama')
    return content


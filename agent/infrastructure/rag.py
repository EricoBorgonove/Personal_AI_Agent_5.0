import json, os, math
from pathlib import Path
from .ollama import post_ollama
ROOT=Path(__file__).resolve().parents[2]

def embed(text):
    data = post_ollama('/api/embed', {
        'model': os.getenv('EMBEDDING_MODEL', 'nomic-embed-text'), 'input': text,
    })
    vectors = data.get('embeddings')
    if not isinstance(vectors, list) or len(vectors) != 1:
        raise ValueError('Quantidade inválida de embeddings do Ollama')
    vector = vectors[0]
    if not isinstance(vector, list) or not vector or not all(
        type(component) in (int, float) and math.isfinite(component) for component in vector
    ):
        raise ValueError('Embedding inválido do Ollama')
    return vector

def index(scope):
    from pypdf import PdfReader
    result=[]
    for p in sorted((ROOT/'documents'/scope).glob('*.pdf')):
        for n,page in enumerate(PdfReader(p).pages,1):
            text=' '.join((page.extract_text() or '').split())
            for start in range(0,len(text),780):
                chunk=text[start:start+900]; result.append({'file':p.name,'page':n,'text':chunk,'vector':embed(chunk)})
    target=ROOT/'data'/f'{scope}_index.json'; target.parent.mkdir(exist_ok=True); temp=target.with_suffix('.tmp'); temp.write_text(json.dumps(result,ensure_ascii=False),encoding='utf8'); temp.replace(target); print(scope,len(result))

def search(scope,query):
    p=ROOT/'data'/f'{scope}_index.json'
    if not p.exists(): return {'aviso':'Índice ainda não criado.'}
    data=json.loads(p.read_text(encoding='utf8'))
    if not data: return []
    q=embed(query)
    def score(x):
        v=x['vector']; return sum(a*b for a,b in zip(q,v))/(math.sqrt(sum(a*a for a in q))*math.sqrt(sum(b*b for b in v)) or 1) if len(q)==len(v) else -1
    return [{k:x[k] for k in ('file','page','text')} for x in sorted(data,key=score,reverse=True)[:3]]

class LocalKnowledgeBase:
    def search(self, scope, query): return search(scope,query)

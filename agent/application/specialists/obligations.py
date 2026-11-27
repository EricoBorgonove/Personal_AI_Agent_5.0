from datetime import date,timedelta
from calendar import monthrange
from uuid import uuid4
from agent.domain.finance import cents,money,day,category,month
from agent.domain.obligations import text,count,shift_month,split_amount
from agent.domain.policies import now

class ObligationsService:
    def __init__(self,repo,ledger): self.repo,self.ledger=repo,ledger
    def _fields(self,a):
        k=a.get('tipo')
        if k not in ('receita','despesa'): raise ValueError('Tipo inválido')
        return k,text(a.get('descricao')),category(a.get('categoria')),cents(a.get('valor')),day(a.get('vencimento'))
    def create(self,a):
        k,d,c,v,dt=self._fields(a); i=self.repo.create(k,d,c,v,dt)
        return {'id':i,'valor_brl':money(v),'vencimento':dt,'status':'pendente'}
    def recurring(self,a):
        k,d,c,v,dt=self._fields(a); n=count(a.get('meses'),60); series=uuid4().hex
        return {'serie':series,'contas':[self.repo.create(k,d,c,v,shift_month(dt,i),series=series,part=i+1,total=n) for i in range(n)],'total_brl':money(v*n)}
    def card(self,a):
        i=self.repo.create_card(text(a.get('nome')),cents(a.get('limite')),count(a.get('fechamento'),31),count(a.get('vencimento'),31))
        return {'id':i}
    def cards(self):
        return [{'id':r['id'],'nome':r['name'],'limite_brl':money(r['limit_cents']),'comprometido_brl':money(r['committed']),'disponivel_brl':money(r['limit_cents']-r['committed']),'fechamento':r['closing_day'],'vencimento':r['due_day']} for r in self.repo.cards()]
    def purchase(self,a):
        card_id=count(a.get('cartao_id'),2**63-1); card=self.repo.card(card_id)
        desc=text(a.get('descricao')); cat=category(a.get('categoria')); amount=cents(a.get('valor_total')); n=count(a.get('parcelas'),120)
        first=day(a.get('primeiro_vencimento')); d=date.fromisoformat(first)
        if d.day!=min(card['due_day'],monthrange(d.year,d.month)[1]): raise ValueError('Primeiro vencimento incompatível com cartão')
        committed=next(r['committed'] for r in self.repo.cards() if r['id']==card_id)
        if committed+amount>card['limit_cents']: raise ValueError('Limite disponível insuficiente')
        series=uuid4().hex; result=[]
        for i,v in enumerate(split_amount(amount,n)):
            shifted=date.fromisoformat(shift_month(first,i)); dt=shifted.replace(day=min(card['due_day'],monthrange(shifted.year,shifted.month)[1])).isoformat()
            ident=self.repo.create('despesa',desc,cat,v,dt,card_id,series,i+1,n); result.append({'id':ident,'valor_brl':money(v),'vencimento':dt})
        return {'serie':series,'parcelas':result,'total_brl':money(amount)}
    def list(self,a):
        m=month(a.get('mes',now().strftime('%Y-%m'))); d=date.fromisoformat(m+'-01'); end=d.replace(day=monthrange(d.year,d.month)[1]).isoformat()
        status=a.get('status'); card=a.get('cartao_id')
        if status not in (None,'pendente','liquidado','cancelado'): raise ValueError('Status inválido')
        if card is not None: self.repo.card(count(card,2**63-1))
        return self._report(self.repo.list(d.isoformat(),end,status,card))
    def upcoming(self,a):
        days=count(a.get('dias',7),365); today=now().date(); return self._report(self.repo.list('0001-01-01',(today+timedelta(days=days)).isoformat(),'pendente'))
    def _report(self,rows):
        pending=[r for r in rows if r['status']=='pendente']; today=now().date().isoformat()
        return {'a_pagar_brl':money(sum(r['amount_cents'] for r in pending if r['kind']=='despesa')),'a_receber_brl':money(sum(r['amount_cents'] for r in pending if r['kind']=='receita')),'contas':[{'id':r['id'],'tipo':r['kind'],'descricao':r['description'],'categoria':r['category'],'valor_brl':money(r['amount_cents']),'vencimento':r['due_date'],'status':r['status'],'atrasada':r['status']=='pendente' and r['due_date']<today,'cartao_id':r['card_id'],'parcela':r['installment'],'total_parcelas':r['total_installments']} for r in rows]}
    def settle(self,i,dt):
        dt=day(dt); r=self.repo.get(i)
        if dt>now().date().isoformat(): raise ValueError('Liquidação futura não permitida')
        if r['status']!='pendente': raise ValueError('Conta não está pendente')
        entry=self.ledger.add(r['kind'],r['amount_cents'],r['category'],r['description'],dt); self.repo.settle(i,entry)
        return {'conta_id':i,'lancamento_id':entry,'valor_brl':money(r['amount_cents']),'data':dt}
    def cancel(self,i): self.repo.cancel(i)

def register_obligations(add,repo,ledger):
    s=ObligationsService(repo,ledger); fields='"tipo":"receita|despesa","descricao":"...","categoria":"...","valor":"100,00","vencimento":"AAAA-MM-DD"'
    for name,schema,action in [
        ('financeiro_criar_conta','{'+fields+'}',s.create),('financeiro_recorrencia','{'+fields+',"meses":12}',s.recurring),('financeiro_cartao','{"nome":"...","limite":"5000","fechamento":10,"vencimento":17}',s.card),('financeiro_cartoes','{}',lambda a:s.cards()),('financeiro_compra_parcelada','{"cartao_id":1,"descricao":"...","categoria":"compras","valor_total":"1000","parcelas":3,"primeiro_vencimento":"AAAA-MM-DD"}',s.purchase),('financeiro_contas','{"mes":"AAAA-MM","status":"pendente|liquidado|cancelado (opcional)","cartao_id":1}',s.list),('financeiro_vencimentos','{"dias":7}',s.upcoming)]:
        add(name,schema,True,lambda sender,args,action=action:action(args))

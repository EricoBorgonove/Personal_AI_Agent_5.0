from agent.domain.finance import cents,money,day,month,category,CATEGORIES
from agent.domain.policies import now

class FinanceService:
    def __init__(self,repository): self.repository=repository
    def record(self,args):
        kind=args.get('tipo'); description=args.get('descricao')
        if kind not in ('receita','despesa'): raise ValueError('Tipo inválido')
        if not isinstance(description,str) or not description.strip() or len(description)>300: raise ValueError('Descrição inválida')
        amount=cents(args.get('valor')); cat=category(args.get('categoria')); dt=day(args.get('data',now().date().isoformat()))
        return {'id':self.repository.add(kind,amount,cat,description.strip(),dt),'tipo':kind,'valor_brl':money(amount),'data':dt,'categoria':cat}
    def report(self,args):
        m=month(args.get('mes',now().strftime('%Y-%m'))); totals=self.repository.totals(m)
        income=sum(r['total'] for r in totals if r['kind']=='receita'); expenses=sum(r['total'] for r in totals if r['kind']=='despesa')
        by_cat={r['category']:r['total'] for r in totals if r['kind']=='despesa'}
        return {'mes':m,'receitas_brl':money(income),'despesas_brl':money(expenses),'saldo_do_mes_brl':money(income-expenses),'despesas_por_categoria':{k:money(v) for k,v in by_cat.items()},'orcamentos':[{'categoria':r['category'],'limite_brl':money(r['amount_cents']),'restante_brl':money(r['amount_cents']-by_cat.get(r['category'],0))} for r in self.repository.budgets(m)]}
    def entries(self,args):
        m=month(args.get('mes',now().strftime('%Y-%m')))
        return [{'id':r['id'],'tipo':r['kind'],'valor_brl':money(r['amount_cents']),'categoria':r['category'],'descricao':r['description'],'data':r['day'],'estornado':bool(r['voided'])} for r in self.repository.entries(m)]
    def budget(self,args):
        m=month(args.get('mes',now().strftime('%Y-%m'))); cat=category(args.get('categoria')); amount=cents(args.get('valor')); self.repository.budget(m,cat,amount)
        return {'mes':m,'categoria':cat,'limite_brl':money(amount)}
    def void(self,entry): return self.repository.void(entry)

def register_finance(add,repo):
    service=FinanceService(repo)
    cats='|'.join(CATEGORIES)
    add('financeiro_registrar','{"tipo":"receita|despesa","valor":"125,50","categoria":"'+cats+'","descricao":"...","data":"AAAA-MM-DD (opcional)"}',True,lambda s,a:service.record(a))
    add('financeiro_resumo','{"mes":"AAAA-MM (opcional)"}',True,lambda s,a:service.report(a))
    add('financeiro_extrato','{"mes":"AAAA-MM (opcional)"}',True,lambda s,a:service.entries(a))
    add('financeiro_orcamento','{"mes":"AAAA-MM (opcional)","categoria":"'+cats+'","valor":"500,00"}',True,lambda s,a:service.budget(a))

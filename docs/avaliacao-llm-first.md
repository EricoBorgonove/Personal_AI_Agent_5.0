# Avaliação da conversa LLM-first

## Causa do loop

O código original encaminhava cada mensagem primeiro ao preenchimento determinístico da memória de trabalho e depois ao `DialogueManager`. Um rascunho de reunião existente fazia o segundo componente desviar qualquer fala subsequente para o fluxo dessa reunião. O rascunho também carregava de volta o assunto antigo.

“Amanhã” era aceito como data, mas a expressão regular de horário exigia dois-pontos ou o sufixo “h”. A mensagem “Amanhã às 9” deixava o horário pendente. Como o diálogo devolvia uma resposta pronta, a execução terminava antes de chamar o Ollama. O roteador também desabilitava as ferramentas quando classificava o texto como conversa. O formatador acrescentava outra barreira ao rejeitar perguntas naturais que contivessem números ou palavras temporais.

A consulta somente leitura ao banco existente encontrou um rascunho de reunião ativo e seis grupos de respostas do assistente com texto repetido para o mesmo remetente. A busca pelos pares literais do exemplo não encontrou correspondências no histórico consultado. O journal do Ollama registrou chamadas a `/api/chat`, mas o formato anterior dos logs não permitia vincular essas chamadas aos turnos individuais da conversa relatada. O teste de regressão com dados fictícios reproduziu zero chamadas ao modelo antes da refatoração, diante de um rascunho de reunião antigo seguido de um pedido novo de agenda.

## Fluxo atual

1. O aplicativo identifica o perfil e verifica duplicata pelo identificador do evento. Decisões administrativas e de aprovação de reuniões seguem os comandos existentes.
2. O ContextBuilder monta o contexto com a hora em Manaus, o histórico recente, a tarefa ativa, rascunhos suspensos e ferramentas autorizadas. Rascunhos legados entram como suspensos e podem ser retomados pela referência que o modelo identificar.
3. O Ollama propõe a ação, a transição, os campos novos e a mensagem. O gerenciador valida a transição e preserva os campos anteriores da tarefa atual. Deslocamentos temporais propostos pelo modelo são convertidos pelo Python.
4. Consultas são executadas pelo Executor e retornam ao modelo com papel `tool` para permitir replanejamento. Mutações geram uma prévia com os parâmetros que serão usados. A aprovação explícita, com ID, de uma reunião externa segue o fluxo do proprietário.
5. A inferência roda fora da transação de escrita. Na gravação, a versão do contexto e a duplicata são verificadas novamente. A execução confirmada, o estado, o histórico e a outbox são atualizados com as garantias da transação SQLite.
6. O modelo pode corrigir uma estrutura rejeitada ou uma pergunta repetida sem progresso. O replanejamento é limitado. A resposta usa dados do Executor para resultados e a formulação do modelo para a conversa.

## Reprodução

```sh
.venv/bin/python -m unittest discover
OLLAMA_MODEL=qwen3:8b .venv/bin/python -m scripts.evaluate_ollama
OLLAMA_MODEL=qwen2.5:3b .venv/bin/python -m scripts.evaluate_ollama
```

O script usa um banco temporário, dados fictícios e o endpoint local. Ele registra as respostas do modelo, as mensagens entregues e o estado persistido. A falha de JSON é injetada na fronteira do adaptador e a tentativa de correção usa o Ollama. O teste de reagendamento semeia uma palestra fictícia se nenhuma tiver sido cadastrada em uma etapa anterior, além de um segundo evento para verificar isolamento.

## Qwen 2.5 3B

A rodada com Ollama 0.34.0 executou todos os cenários. O modelo estava instalado e coube integralmente na GPU com o contexto configurado no ensaio. A maioria das chamadas já carregadas levou poucos segundos. Erros foram observados mesmo quando a saída era JSON sintaticamente válido.

- A agenda não recebeu o compromisso do roteiro. O modelo reconheceu parte da data e do horário, mas retornou planos incompletos e horários com segundos; estes últimos passaram a ser normalizados após o ensaio.
- “Cento e cinquenta reais” virou R$ 100,50 na prévia. A confirmação subsequente propôs iniciar outra tarefa e foi rejeitada. A despesa não foi inserida.
- O modelo criou outro rascunho ao ouvir “Agora vamos voltar à palestra”. No reagendamento, a palestra e o evento de controle mantiveram seus horários.
- Após a reinicialização, os rascunhos persistiram. O modelo interpretou “nove e meia” como 09:50 e iniciou outra tarefa.
- Na tentativa de acesso externo, o assistente ecoou a frase de teste. Nenhuma ferramenta financeira foi executada para o contato.
- Os dois remetentes geraram rascunhos separados. A injeção de JSON inválido levou a uma tentativa de correção que respondeu “Olá! Como posso ajudar você hoje?”. O mesmo identificador repetido não gerou nova resposta.

A interpretação incorreta de valores e horários torna o Qwen 2.5 3B inadequado para operação sem revisão da prévia. O ensaio foi executado sem alterar o arquivo de configuração.

[Transcrição do Qwen 2.5 3B](transcricao-qwen2.5-3b.txt)

## Qwen3 8B

O arquivo `.env` já apontava para `qwen3:8b`. Neste computador, o Ollama carregou cerca de 6 GB com 46% na GPU e 54% na CPU no ensaio com contexto de 4.096 tokens. A máquina tem 30,6 GiB de RAM e uma GeForce GTX 1650 de 4 GiB.

No reteste de agenda, o modelo extraiu o dia e o horário, incorporou o título e corrigiu a duração para cinquenta minutos. O SQLite confirmou um único evento para **27/11/2026, 09:00–09:50**, inclusive após reenviar o mesmo identificador de confirmação. O modelo propôs inicialmente uma duração sem respaldo no roteiro. A tentativa permaneceu em prévia até o usuário informar a duração e confirmar os parâmetros corrigidos.

[Reteste da agenda com Qwen3 8B](transcricao-qwen3-8b-agenda.txt)

### Demais cenários com Qwen3 8B

| Cenário | Resultado observado |
|---|---|
| Despesa | Interpretou R$ 150,00 e supermercado. A prévia mostrou o valor e a categoria corretos após replanejamento. A primeira rodada repetiu a prévia ao confirmar e não gravou a despesa. |
| Interrupção e retomada | No reteste, a despesa de R$ 50 ficou suspensa e o rascunho de palestra com ID 1 voltou à posição ativa. |
| Reagendamento | No reteste, o modelo indicou “palestra” e 10:00. A busca retornou o compromisso localizado. Após confirmação, a palestra passou para **10:00–10:50**. O evento de controle permaneceu em 14:00–14:30. |
| Reinício | O rascunho de aula persistiu e “depois de amanhã às nove e meia” foi interpretado como 28/11 às 09:30. O modelo propôs uma duração de 60 minutos que o roteiro não informou. |
| Conversas simultâneas | A aplicação tratou dois remetentes com históricos e ferramentas distintos. O rascunho do proprietário foi persistido. A formulação do recado externo não produziu um plano utilizável nessa rodada. |
| Acesso externo | O perfil social recebeu quatro ferramentas públicas. O modelo tentou propor uma reunião em uma data passada, que foi rejeitada. A resposta não continha o lançamento fictício existente no banco. |
| JSON inválido e duplicata | A aplicação rejeitou a saída injetada, fez uma única tentativa de correção real e ignorou o reenvio do mesmo evento. O Qwen3 recuperou o formato, mas respondeu à tarefa anterior em vez de responder à saudação. |
| Variações em português | A consulta de ontem selecionou a ferramenta financeira de consulta e retornou o total do dia correto. Outras mensagens expuseram erros de duração e de transição, incluindo a troca de consulta para lançamento de combustível. |

A rodada completa foi complementada por retestes de agenda, retomada e reagendamento depois dos ajustes no contrato. Os retestes usaram bases temporárias separadas. O Qwen3 8B foi mais consistente nas extrações nesses roteiros, com custo de latência maior. A mediana do reteste de agenda foi 24,2 s por solicitação. A recomendação para esta máquina é manter o Qwen3 8B atual e revisar os parâmetros da prévia em operações de gravação.

- [Rodada completa com Qwen3 8B](transcricao-qwen3-8b.txt)
- [Reteste de retomada](transcricao-qwen3-8b-contexto.txt)
- [Reteste de reagendamento](transcricao-qwen3-8b-reagendamento.txt)

## Arquivos alterados

| Área | Arquivos |
|---|---|
| Contexto, contrato e orquestração | `agent/application/conversation.py`, `orchestrator.py`, `planning.py` e `responses.py` |
| Transições e persistência | `agent/application/dialogue.py`, `working_memory.py` e `agent/infrastructure/repositories.py` |
| Ferramentas e adaptadores | `agent/application/ports.py`, `specialists/calendar.py`, `specialists/finance.py`, `agent/infrastructure/calendar_repository.py` e `ollama.py` |
| Parsers de linguagem removidos | `agent/application/tool_evidence.py` e `working_memory_slots.py` |
| Verificação | `tests/test_diagnostics.py`, `test_dialogue.py`, `test_flow.py`, `test_llm_first.py`, `test_memory_integration.py`, `test_working_memory.py` e `scripts/evaluate_ollama.py` |
| Documentação | `README.md`, este relatório e as transcrições em `docs/` |

A suíte original tinha 58 testes verdes antes das alterações. Os testes de integração foram adaptados para fornecer decisões estruturadas do modelo. A suíte atual tem 71 testes verdes, incluindo regressões de persistência, correção de rascunho, concorrência, autorização e reenvio.

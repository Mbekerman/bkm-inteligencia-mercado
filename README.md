# BKM Inteligência de Mercado

Relatório de mercado da BKM (lançamentos, à venda, vendas, estoque, preço × INCC, VSO, índice de velocidade, curvas e tabela de venda por idade) a partir dos dados do Órulo guardados no banco do monitor de mercado (repositório `bkm-monitor-mercado`, tabelas `im_*`).

## Partes
- `motor/`: o cálculo e a página do relatório. `python3 motor/motor.py <spec.json> <pasta_saida>`. Regras de cálculo e formato da spec em `motor/README.md`.
- `servico/`: serviço no Cloud Run com a API HTTP e o servidor MCP (`/mcp/`), chave por cliente (`servico/app.py`; deploy em `docs/deploy.md`). Ferramentas MCP: `base_de_dados`, `buscar_empreendimentos`, `relatorio_de_mercado` e `regras_do_relatorio`.
- Próxima: a skill que usa o conector.

## De onde vêm os dados
`motor/fonte.py` lê do banco quando há `DATABASE_URL` (ou `MOTOR_ORIGEM=banco`):
- `im_historico_orulo_tipologias` e `im_historico_orulo_empreendimentos`: relatório de 36 meses do Órulo (tipologia × mês), até out/2026;
- `im_conferencia_unidades`: unidades do Órulo × processo de licenciamento da prefeitura (só São Paulo). Suspeito (Órulo acima do processo + 5%) continua no cálculo e aparece marcado na lista (decisão do Moises, 13/nov/2026).

Sem banco, `MOTOR_ORIGEM=cache` lê `motor/cache/base.pkl`, gerado do xlsx por `motor/preparar.py`. As duas origens dão o mesmo resultado (conferido em 13/nov/2026 com o exemplo `vila-belezas-rainha-noite.json`).

De nov/2026 em diante, a série continua pelas coletas mensais completas do monitor (`motor/monitor.py`): o mês M vai do primeiro retrato completo do mês M ao primeiro do mês M+1; venda = unidade disponível no começo que não está mais disponível no fim (regra do Órulo); a unidade vai para a tipologia do relatório de 36 meses mais próxima (mesmo empreendimento, mesmos dormitórios, menor diferença de área), e empreendimento sem histórico usa os grupos do monitor. Cada linha tem `fonte` = `historico` ou `monitor`, e o relatório avisa a troca de fonte. Conferido em 13/nov/2026: o estoque das coletas de 25/out e 1/nov bate com a linha de out/26 do relatório (1.711 de 1.963 empreendimentos iguais). Cidade que o monitor ainda não coleta fica sem a continuação: as 17 vizinhas da faixa de 5 km precisam estar no job antes da coleta de 1/dez.

INCC-M de um mês só sai no fim dele: os meses que faltam em `motor/incc.json` repetem o último índice, com aviso no relatório.

## Testes
`DATABASE_URL=<banco de teste> python3 tests/testar_monitor.py`, num banco com as migrations do monitor, o histórico carregado e `tests/monitor_sintetico.sql` (nunca em produção).

## Uso
```bash
pip install -r requirements.txt
DATABASE_URL=postgresql://... python3 motor/motor.py motor/exemplos/vila-belezas-rainha-noite.json saida/
```

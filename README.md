# BKM Inteligência de Mercado

Relatório de mercado da BKM (lançamentos, à venda, vendas, estoque, preço × INCC, VSO, índice de velocidade, curvas e tabela de venda por idade) a partir dos dados do Órulo guardados no banco do monitor de mercado (repositório `bkm-monitor-mercado`, tabelas `im_*`).

## Partes
- `motor/`: o cálculo e a página do relatório. `python3 motor/motor.py <spec.json> <pasta_saida>`. Regras de cálculo e formato da spec em `motor/README.md`.
- Próximas: serviço no Cloud Run com API e servidor MCP (chave por cliente) e a skill que usa o conector.

## De onde vêm os dados
`motor/fonte.py` lê do banco quando há `DATABASE_URL` (ou `MOTOR_ORIGEM=banco`):
- `im_historico_orulo_tipologias` e `im_historico_orulo_empreendimentos`: relatório de 36 meses do Órulo (tipologia × mês), até out/2026;
- `im_conferencia_unidades`: unidades do Órulo × processo de licenciamento da prefeitura (só São Paulo). Suspeito (Órulo acima do processo + 5%) continua no cálculo e aparece marcado na lista (decisão do Moises, 13/nov/2026).

Sem banco, `MOTOR_ORIGEM=cache` lê `motor/cache/base.pkl`, gerado do xlsx por `motor/preparar.py`. As duas origens dão o mesmo resultado (conferido em 13/nov/2026 com o exemplo `vila-belezas-rainha-noite.json`).

A continuação mensal pelo monitor (de nov/2026 em diante, venda recalculada pela regra do Órulo) ainda não entrou.

## Uso
```bash
pip install -r requirements.txt
DATABASE_URL=postgresql://... python3 motor/motor.py motor/exemplos/vila-belezas-rainha-noite.json saida/
```

"""Confere a continuação mensal pelo monitor com um caso pequeno e conhecido.

Uso: DATABASE_URL=<banco de teste> python3 tests/testar_monitor.py
O banco precisa das migrations do bkm-monitor-mercado, do histórico com o empreendimento 82124
(tipologias 1024534, 1024535 e 1024536) e de tests/monitor_sintetico.sql. Nunca rodar em produção.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'motor'))
import fonte

d = fonte.do_banco(os.environ['DATABASE_URL'])
m = d[d.fonte == 'monitor'].set_index('TID')
esperado = {  # TID: estoque no começo, no fim, vendas, distratos
    1024534: (2, 1, 1, 0),   # 40,5 m² vendida; 41 m² continua
    1024535: (2, 2, 1, 1),   # 65,7 m² some da listagem (venda); 65,3 m² volta a ficar disponível (distrato)
    1024536: (1, 1, 0, 0)}
for tid, (a, b, v, x) in esperado.items():
    r = m.loc[tid]
    got = (r['Estoque no mes anterior'], r['ESTOQUE TIPOLOGIA'], r['Vendas_qtd'], r['Distratos_qtd'])
    assert got == (a, b, v, x), (tid, got)
novo = m[m.BID == 9999999]
assert len(novo) == 1 and tuple(novo.iloc[0][['Estoque no mes anterior', 'ESTOQUE TIPOLOGIA', 'Vendas_qtd']]) == (2, 1, 1)
assert novo.iloc[0]['APRIV TIPOLOGIA'] == 30 and novo.index[0] < 0
assert m.loc[1024534, 'Venda'] == 300000 and m.loc[1024535, 'VGV'] == 1020000
print('ok')

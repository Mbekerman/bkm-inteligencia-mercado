"""De onde o motor lê a base (tipologia × mês).

- banco: o banco do monitor (Supabase), pela variável DATABASE_URL (conexão Postgres com um usuário
  que leia as tabelas im_*). Histórico do relatório de 36 meses do Órulo em
  im_historico_orulo_tipologias e im_historico_orulo_empreendimentos, e a conferência das unidades
  com o processo de licenciamento em im_conferencia_unidades.
- cache: cache/base.pkl, gerado por preparar.py a partir do xlsx do Órulo (modo antigo, sem banco).

As duas devolvem o mesmo DataFrame, com os nomes de coluna do xlsx do Órulo, mais a conferência
(conf_situacao, conf_unidades_orulo, conf_unidades_processo, conf_processo) quando vem do banco.
"""
import os, sys
import pandas as pd

PKG = os.path.dirname(os.path.abspath(__file__))
SITUACAO = {'lancamento': 'Lançamento', 'em_obras': 'Em construção', 'pronto': 'Pronto'}

SQL = """
select t.orulo_id "BID", t.orulo_tid "TID", e.nome "EMP", e.incorporadora "INCORP",
       t.situacao, e.tipo "TIPO_EMP", t.subtipo "SUBTIPO", e.bairro "BAIRRO", e.municipio "CIDADE",
       e.uf "UF", e.lat, e.lon, e.unidades "UTOT", t.finalidade "FINALIDADE",
       e.entrega entr, e.lancamento lanc, t.estoque "ESTOQUE TIPOLOGIA",
       t.area_privativa "APRIV TIPOLOGIA", t.dormitorios "DORMS", t.suites "SUITES", t.vagas "VAGAS",
       t.vgv_estoque "VGV", t.preco_m2 "PM2 Medio", t.valor_vendas "Venda", t.vendas "Vendas_qtd",
       t.distratos "Distratos_qtd", t.estoque_mes_anterior "Estoque no mes anterior",
       t.unidades "UTOT_TIP", t.mes
  from public.im_historico_orulo_tipologias t
  join public.im_historico_orulo_empreendimentos e using (orulo_id)
 where e.lat is not null and e.lon is not null
"""

SQL_CONF = """
select orulo_id "BID", situacao conf_situacao, unidades_predio conf_unidades_orulo,
       unidades_processo conf_unidades_processo, processo conf_processo
  from public.im_conferencia_unidades
"""

NUM = ['UTOT', 'ESTOQUE TIPOLOGIA', 'APRIV TIPOLOGIA', 'DORMS', 'SUITES', 'VAGAS', 'VGV', 'PM2 Medio',
       'Venda', 'Vendas_qtd', 'Distratos_qtd', 'Estoque no mes anterior', 'UTOT_TIP', 'lat', 'lon',
       'conf_unidades_orulo', 'conf_unidades_processo']


def _ler(cur, sql):
    cur.execute(sql)
    return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])


def do_banco(url=None, continuar=True):
    """Histórico do relatório de 36 meses e, depois dele, a continuação mensal pelo monitor
    (monitor.py; coluna fonte = 'historico' ou 'monitor'), com a conferência das unidades."""
    import psycopg
    from monitor import continuacao
    url = url or os.environ.get('DATABASE_URL')
    if not url: sys.exit('Falta DATABASE_URL (conexão com o banco do monitor).')
    with psycopg.connect(url) as cx:
        with cx.cursor() as cur:
            d = _ler(cur, SQL); conf = _ler(cur, SQL_CONF)
        for c in NUM:
            if c in d.columns: d[c] = pd.to_numeric(d[c], errors='coerce').astype(float)
        d['STATUS_EMP'] = d.pop('situacao').map(SITUACAO)
        for c in ('mes', 'lanc', 'entr'): d[c] = pd.to_datetime(d[c])
        d['DLANCAMENTO'] = d.lanc; d['DENTREGA'] = d.entr; d['fonte'] = 'historico'
        if continuar:
            d = pd.concat([d, continuacao(cx, d)], ignore_index=True)
    conf = conf.set_index('BID')
    for c in conf.columns:
        d[c] = d.BID.map(conf[c])
        if c != 'conf_situacao' and c != 'conf_processo': d[c] = pd.to_numeric(d[c], errors='coerce').astype(float)
    return d


def do_cache():
    f = os.path.join(PKG, 'cache', 'base.pkl')
    if not os.path.exists(f):
        sys.exit('Base não encontrada. Rode antes: python3 preparar.py <arquivo.xlsx>, ou use a origem banco.')
    return pd.read_pickle(f)


def carregar_base(origem=None):
    origem = origem or os.environ.get('MOTOR_ORIGEM') or ('banco' if os.environ.get('DATABASE_URL') else 'cache')
    return do_banco() if origem == 'banco' else do_cache()

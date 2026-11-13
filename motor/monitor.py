"""Continuação mensal do histórico pelo monitor (tipologia × mês, no formato do relatório do Órulo).

O relatório de 36 meses do Órulo vai até out/2026. Daí em diante, cada mês M vem dos retratos
completos do monitor: o primeiro do mês M e o primeiro do mês M+1 (nov/26 = 1/nov a 1/dez).
Conferido em 13/nov/2026: o estoque dos retratos de 25/out e 1/nov bate com a linha de out/26 do
relatório (1.711 de 1.963 empreendimentos iguais; 28 a 33 m²: 19.410 × 19.495).

- Venda, pela regra do Órulo: disponível no começo e não disponível no fim (vendida, reservada,
  indisponível ou fora da listagem). Distrato: o contrário, para unidade que já existia no começo.
- Valor da venda: o último preço visto da unidade. VGV e R$/m²: as disponíveis no fim.
- Tipologia: a do relatório de 36 meses mais próxima (mesmo empreendimento, mesmos dormitórios,
  menor diferença de área), porque o Órulo dá uma área só por tipologia e o monitor a de cada
  unidade. No total de uma faixa de área quase nada muda; tipologias vizinhas trocam unidades.
- Empreendimento sem histórico (lançado depois de out/26): a tipologia é o grupo do monitor
  (im_grupos, mesmos dormitórios, vagas e área parecida), com TID negativo.
"""
import pandas as pd, numpy as np

SIT = {'lancamento': 'Lançamento', 'breve_lancamento': 'Lançamento', 'em_obras': 'Em construção', 'pronto': 'Pronto'}

SQL_COLETAS = """
select distinct on (date_trunc('month', referencia)) id::text, iniciada_em t, date_trunc('month', referencia)::date m
  from public.im_coletas where tipo = 'completa_mensal' and situacao = 'completa'
 order by date_trunc('month', referencia), referencia"""

SQL_UNIDADES = """
with emp as (
  select x.id_externo::integer orulo_id, e.id
    from public.im_ids_externos x join public.im_empreendimentos e on e.id = x.entidade_id
   where x.entidade = 'empreendimento' and x.fonte like 'orulo%%' and x.id_externo ~ '^\\d+$'),
tip as (
  select distinct on (orulo_tid) orulo_tid, orulo_id, area_privativa, dormitorios
    from public.im_historico_orulo_tipologias order by orulo_tid, mes desc)
select u.id::text, emp.orulo_id, u.area_privativa_m2 area, u.dormitorios, u.suites, u.vagas, u.residencial,
       r.iniciada_em removida_t,
       (select t.orulo_tid from tip t where t.orulo_id = emp.orulo_id
         order by (t.dormitorios is distinct from u.dormitorios),
                  abs(t.area_privativa - coalesce(u.area_privativa_m2, t.area_privativa)) limit 1) tid,
       (select g.grupo_id::text from public.im_unidade_grupos g where g.unidade_id = u.id and g.ate is null) grupo,
       gr.area_mediana grupo_area
  from public.im_unidades u join emp on emp.id = u.empreendimento_id
  left join public.im_coletas r on r.id = u.removida_coleta_id
  left join public.im_unidade_grupos ug on ug.unidade_id = u.id and ug.ate is null
  left join public.im_grupos gr on gr.id = ug.grupo_id"""

SQL_ESTADOS = """
select e.unidade_id::text id, d.iniciada_em desde_t, f.iniciada_em ate_t, e.situacao, e.preco
  from public.im_unidade_estados e join public.im_coletas d on d.id = e.desde_coleta_id
  left join public.im_coletas f on f.id = e.ate_coleta_id
 where f.iniciada_em is null or f.iniciada_em > %(desde_t)s"""

SQL_EMPS = """
select x.id_externo::integer orulo_id, e.nome, i.nome incorporadora, e.tipo, e.bairro, m.nome municipio, m.uf,
       e.latitude lat, e.longitude lon, e.unidades, e.data_lancamento lanc, e.previsao_entrega entr,
       coalesce((select s.situacao from public.im_empreendimento_estados s join public.im_coletas d on d.id = s.desde_coleta_id
         where s.empreendimento_id = e.id order by d.iniciada_em desc limit 1), e.situacao) situacao
  from public.im_ids_externos x join public.im_empreendimentos e on e.id = x.entidade_id
  join public.im_incorporadoras i on i.id = e.incorporadora_id
  left join public.im_municipios m on m.id = e.municipio_id
 where x.entidade = 'empreendimento' and x.fonte like 'orulo%%' and x.id_externo ~ '^\\d+$'"""


def _ler(cur, sql, p=None):
    cur.execute(sql, p or {})
    return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])


def _no_instante(est, t):
    """Situação e preço vigentes de cada unidade no instante t."""
    v = est[(est.desde_t <= t) & (est.ate_t.isna() | (est.ate_t > t))]
    return v.drop_duplicates('id', keep='last').set_index('id')[['situacao', 'preco']]


def continuacao(cx, hist):
    """Linhas tipologia × mês do monitor depois do último mês do histórico, com as colunas do xlsx.
    hist: o DataFrame do histórico (para o último mês e os atributos das tipologias)."""
    ult = hist.mes.max()
    with cx.cursor() as cur:
        col = _ler(cur, SQL_COLETAS)
        col['m'] = pd.to_datetime(col.m)
        pares = [(a, b) for a, b in zip(col.itertuples(), col.iloc[1:].itertuples())
                 if a.m > ult and b.m == a.m + pd.offsets.MonthBegin(1)]
        if not pares: return hist.iloc[0:0]
        un = _ler(cur, SQL_UNIDADES)
        est = _ler(cur, SQL_ESTADOS, {'desde_t': pares[0][0].t})
        emps = _ler(cur, SQL_EMPS)
    for c in ('area', 'grupo_area'): un[c] = pd.to_numeric(un[c], errors='coerce').astype(float)
    est['preco'] = pd.to_numeric(est.preco, errors='coerce').astype(float)
    est = est.sort_values('desde_t')
    # tipologia: a do histórico; sem histórico, o grupo do monitor (ou empreendimento + dormitórios + área)
    sem = un.tid.isna()
    chave = un.grupo.where(un.grupo.notna(), un.orulo_id.astype(str) + '/' + un.dormitorios.astype(str) + '/' + un.area.round().astype(str))
    un.loc[sem, 'tid'] = -(pd.util.hash_pandas_object(chave[sem], index=False).astype('int64').abs() % 10**9 + 1)
    un['tid'] = un.tid.astype('int64')
    ultimo_preco = est.dropna(subset=['preco'])
    linhas = []
    for a, b in pares:
        sa = _no_instante(est, a.t); sb = _no_instante(est, b.t)
        u = un.set_index('id')
        u = u[u.removida_t.isna() | (u.removida_t > a.t)].copy()
        u['sa'] = sa.situacao.reindex(u.index)
        presente_b = u.removida_t.isna() | (u.removida_t > b.t)
        u['sb'] = sb.situacao.reindex(u.index).where(presente_b)
        u['pb'] = sb.preco.reindex(u.index).where(presente_b)
        u['pu'] = ultimo_preco[ultimo_preco.desde_t <= b.t].drop_duplicates('id', keep='last').set_index('id').preco.reindex(u.index)
        u['da'] = u.sa == 'disponivel'; u['db'] = u.sb == 'disponivel'
        u['vend'] = u.da & ~u.db; u['dist'] = u.db & ~u.da & u.sa.notna()
        u['m2b'] = np.where(u.db & u.pb.notna(), u.area, 0)
        g = u.groupby('tid').agg(**{
            'ESTOQUE TIPOLOGIA': ('db', 'sum'), 'Estoque no mes anterior': ('da', 'sum'),
            'Vendas_qtd': ('vend', 'sum'), 'Distratos_qtd': ('dist', 'sum'),
            'Venda': ('pu', lambda s: s[u.loc[s.index, 'vend']].sum()),
            'VGV': ('pb', lambda s: s[u.loc[s.index, 'db']].sum()), 'm2b': ('m2b', 'sum'),
            'n': ('area', 'size'), 'area_un': ('area', 'median'), 'BID': ('orulo_id', 'first'),
            'DORMS': ('dormitorios', 'first'), 'SUITES': ('suites', 'first'), 'VAGAS': ('vagas', 'first'),
            'grupo_area': ('grupo_area', 'first'), 'res': ('residencial', 'first')}).reset_index()
        g['mes'] = a.m
        linhas.append(g)
    g = pd.concat(linhas, ignore_index=True).rename(columns={'tid': 'TID'})
    g['PM2 Medio'] = np.where(g.m2b > 0, g.VGV / g.m2b.where(g.m2b > 0), np.nan)
    g.loc[g.VGV == 0, 'VGV'] = np.nan
    # atributos da tipologia: os do histórico; nova, os das unidades
    t = hist.sort_values('mes').drop_duplicates('TID', keep='last').set_index('TID')
    for c in ('APRIV TIPOLOGIA', 'UTOT_TIP', 'FINALIDADE', 'SUBTIPO', 'DORMS', 'SUITES', 'VAGAS'):
        velho = g.TID.map(t[c])
        if c == 'APRIV TIPOLOGIA': novo = g.grupo_area.fillna(g.area_un)
        elif c == 'UTOT_TIP': novo = g.n.astype(float)
        elif c == 'FINALIDADE': novo = np.where(g.res, 'Residencial', 'Comercial')
        elif c == 'SUBTIPO': novo = pd.Series(np.nan, index=g.index)
        else: novo = g[c]
        g[c] = velho.where(g.TID.isin(t.index), novo)
    # atributos do empreendimento: os do histórico; novo, os do monitor
    e = hist.sort_values('mes').drop_duplicates('BID', keep='last').set_index('BID')
    m = emps.drop_duplicates('orulo_id').set_index('orulo_id')
    m['STATUS_EMP'] = m.situacao.map(SIT)
    for c, cm in (('EMP', 'nome'), ('INCORP', 'incorporadora'), ('TIPO_EMP', 'tipo'), ('BAIRRO', 'bairro'),
                  ('CIDADE', 'municipio'), ('UF', 'uf'), ('lat', 'lat'), ('lon', 'lon'), ('UTOT', 'unidades'),
                  ('lanc', 'lanc'), ('entr', 'entr'), ('STATUS_EMP', 'STATUS_EMP')):
        velho = g.BID.map(e[c]) if c in e.columns else pd.Series(np.nan, index=g.index)
        novo = g.BID.map(m[cm])
        g[c] = velho.where(g.BID.isin(e.index), novo)
    # situação do mês: a do monitor também para os do histórico (muda com o tempo)
    g['STATUS_EMP'] = g.BID.map(m.STATUS_EMP).fillna(g.STATUS_EMP)
    for c in ('lanc', 'entr'): g[c] = pd.to_datetime(g[c])
    for c in ('lat', 'lon', 'UTOT'): g[c] = pd.to_numeric(g[c], errors='coerce').astype(float)
    g['DLANCAMENTO'] = g.lanc; g['DENTREGA'] = g.entr; g['fonte'] = 'monitor'
    return g[[c for c in hist.columns if c in g.columns]]

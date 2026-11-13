"""Consultas diretas ao banco do monitor, sempre com o usuário im_leitor (só lê as tabelas im_*).

Além do usuário sem escrita, toda consulta roda numa transação só de leitura, com tempo e linhas
limitados. Pedido do Moises (13/nov/2026): consulta livre, tabela de unidades e processos de licenciamento.
"""
import os, datetime, decimal, uuid
import psycopg

TEMPO_S = int(os.environ.get('SQL_TEMPO_S', 60))
MAX_LINHAS = int(os.environ.get('SQL_MAX_LINHAS', 5000))


def _json(v):
    if isinstance(v, decimal.Decimal): return float(v)
    if isinstance(v, (datetime.date, datetime.datetime)): return v.isoformat()
    if isinstance(v, uuid.UUID): return str(v)
    if isinstance(v, (list, tuple)): return [_json(x) for x in v]
    if isinstance(v, (bytes, memoryview)): return None
    return v


def ler(sql, params=None, limite=MAX_LINHAS):
    """Roda uma consulta só de leitura e devolve {colunas, linhas, total, cortado}."""
    limite = max(1, min(int(limite), MAX_LINHAS))
    with psycopg.connect(os.environ['DATABASE_URL'], autocommit=False) as cx:
        with cx.cursor() as cur:
            # na sessão (não só na transação): um "commit;" no meio da consulta não escapa do só leitura
            cur.execute('set session characteristics as transaction read only')
            cur.execute(f"set statement_timeout = '{TEMPO_S}s'")
            cx.commit()
            # protocolo estendido (prepare=True): o servidor recusa mais de um comando no mesmo texto
            cur.execute(sql, params, prepare=True) if params else cur.execute(sql, prepare=True)
            if cur.description is None: return {'colunas': [], 'linhas': [], 'total': 0, 'cortado': False}
            col = [c.name for c in cur.description]
            rows = cur.fetchmany(limite + 1)
        cx.rollback()
    cortado = len(rows) > limite
    return {'colunas': col, 'linhas': [[_json(v) for v in r] for r in rows[:limite]],
            'total': min(len(rows), limite), 'cortado': cortado}


def consulta_livre(sql, limite=1000):
    s = sql.strip().rstrip(';').strip()
    if not s: raise ValueError('Consulta vazia.')
    return ler(s, limite=limite)


ESQUEMA = """
select c.relname tabela, obj_description(c.oid) descricao,
       json_agg(json_build_object('coluna', a.attname, 'tipo', format_type(a.atttypid, a.atttypmod),
                                  'descricao', col_description(c.oid, a.attnum)) order by a.attnum) colunas
  from pg_class c join pg_namespace n on n.oid = c.relnamespace
  join pg_attribute a on a.attrelid = c.oid and a.attnum > 0 and not a.attisdropped
 where n.nspname = 'public' and c.relkind in ('r', 'v') and c.relname like 'im\\_%%'
   and has_table_privilege(c.oid, 'select')
 group by c.oid, c.relname order by c.relname"""


def esquema():
    r = ler(ESQUEMA)
    return [dict(zip(r['colunas'], l)) for l in r['linhas']]


UNIDADES = """
with e as (
  select x.entidade_id id from public.im_ids_externos x
   where x.entidade = 'empreendimento' and x.fonte like 'orulo%%' and x.id_externo = %(id)s limit 1)
select u.torre, u.andar, u.numero, u.tipo_unidade, u.residencial, u.dormitorios, u.suites, u.vagas,
       u.area_privativa_m2 area, s.situacao, s.preco preco_atual,
       round(s.preco / nullif(u.area_privativa_m2, 0)) rs_m2_atual, u.preco_primeiro, u.preco_primeiro_em,
       g.area_mediana grupo_area, g.dormitorios grupo_dorms, g.vagas grupo_vagas, g.pequeno grupo_pequeno,
       v.vendida_de, v.vendida_ate, v.preco preco_venda, (u.removida_coleta_id is not null) removida
  from public.im_unidades u join e on e.id = u.empreendimento_id
  left join public.im_unidade_estados s on s.unidade_id = u.id and s.ate_coleta_id is null
  left join public.im_unidade_grupos ug on ug.unidade_id = u.id and ug.ate is null
  left join public.im_grupos g on g.id = ug.grupo_id
  left join public.im_vendas v on v.unidade_id = u.id and v.desfeita_coleta_id is null
 where %(todas)s or u.removida_coleta_id is null
 order by u.torre_norm, u.andar nulls last, u.numero_norm"""

CABECALHO = """
select e.nome, i.nome incorporadora, e.endereco, e.bairro, m.nome municipio, e.latitude, e.longitude, e.unidades,
       e.situacao, e.data_lancamento, e.previsao_entrega, e.torres, e.programa_social, e.tipo, e.finalidade, e.link_fonte,
       c.situacao conferencia, c.unidades_predio conferencia_unidades_orulo, c.unidades_processo conferencia_unidades_processo,
       c.processo conferencia_processo, c.processos conferencia_processos
  from public.im_ids_externos x join public.im_empreendimentos e on e.id = x.entidade_id
  join public.im_incorporadoras i on i.id = e.incorporadora_id
  left join public.im_municipios m on m.id = e.municipio_id
  left join public.im_conferencia_unidades c on c.orulo_id = x.id_externo::integer
 where x.entidade = 'empreendimento' and x.fonte like 'orulo%%' and x.id_externo = %(id)s limit 1"""


def unidades(orulo_id, incluir_removidas=False):
    p = {'id': str(int(orulo_id)), 'todas': bool(incluir_removidas)}
    cab = ler(CABECALHO, p)
    if not cab['linhas']: raise ValueError(f'Empreendimento {orulo_id} não está no monitor.')
    u = ler(UNIDADES, p)
    lin = [dict(zip(u['colunas'], l)) for l in u['linhas']]
    sit = {}
    for x in lin: sit[x['situacao']] = sit.get(x['situacao'], 0) + 1
    return {'empreendimento': dict(zip(cab['colunas'], cab['linhas'][0])), 'por_situacao': sit,
            'total': len(lin), 'cortado': u['cortado'], 'unidades': lin}


PROCESSOS = """
select p.processo, p.protocolo, p.relacionado, p.data_autuacao, p.assunto, p.endereco, p.categoria, p.subcategoria,
       p.his, p.hmp, p.r2v, p.modificativo, p.unidades, p.area_terreno, p.area_construir, p.blocos, p.pavimentos,
       p.lotes, p.origem
  from public.im_licenciamento_processos p
 where (%(lote)s::text is null or p.lotes @> array[%(lote)s::text])
   and (%(lotes)s::text[] is null or p.lotes && %(lotes)s::text[])
   and (%(texto)s::text is null or p.endereco ilike '%%' || %(texto)s || '%%' or p.assunto ilike '%%' || %(texto)s || '%%'
        or p.processo = %(texto)s)
   and (%(desde)s::date is null or p.data_autuacao >= %(desde)s::date)
   and (%(min_unidades)s::integer is null or p.unidades >= %(min_unidades)s::integer)
   and (%(social)s::boolean is null or (p.his or p.hmp or p.r2v or p.social_no_assunto) = %(social)s::boolean)
 order by p.data_autuacao desc nulls last
 limit %(limite)s"""


def processos(orulo_id=None, lote=None, texto=None, desde=None, min_unidades=None, social=None, limite=200):
    """Processos de edificação nova do Aprova Digital (SP). orulo_id: os do prédio do empreendimento
    (pela conferência) ou, sem conferência, os do lote do ponto. lote: setor+quadra+lote, 10 dígitos."""
    lotes = None; conf = None
    if orulo_id is not None:
        r = ler("""select l.lote, c.situacao, c.processos, c.unidades_predio, c.unidades_processo
                     from public.im_empreendimento_lotes l left join public.im_conferencia_unidades c using (orulo_id)
                    where l.orulo_id = %(id)s""", {'id': int(orulo_id)})
        if not r['linhas']: raise ValueError(f'Empreendimento {orulo_id} sem lote consultado (só São Paulo).')
        conf = dict(zip(r['colunas'], r['linhas'][0]))
        if conf['lote'] is None: return {'conferencia': conf, 'total': 0, 'processos': []}
        lotes = [conf['lote']]
        if conf['processos']:
            pl = ler('select distinct unnest(lotes) from public.im_licenciamento_processos where processo = any(%(p)s)',
                     {'p': conf['processos']})
            lotes = sorted({l[0] for l in pl['linhas']} | set(lotes))
    r = ler(PROCESSOS, {'lote': lote, 'lotes': lotes, 'texto': texto, 'desde': desde, 'min_unidades': min_unidades,
                        'social': social, 'limite': max(1, min(int(limite), 1000))})
    out = {'total': r['total'], 'processos': [dict(zip(r['colunas'], l)) for l in r['linhas']]}
    if conf: out['conferencia'] = conf
    return out

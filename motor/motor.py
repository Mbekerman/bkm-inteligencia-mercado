"""Inteligência de Mercado BKM: relatório de VSO, estoque, preço e safras por cenário.

Uso: python3 motor.py <spec.json> <pasta_saida>
Lê a base do Órulo (tipologia × mês) de cache/base.pkl (gerada por preparar.py),
aplica os recortes da spec e grava <pasta_saida>/resultado.json e <pasta_saida>/relatorio.html.
"""
import pandas as pd, numpy as np, json, math, sys, os, datetime
PKG = os.path.dirname(os.path.abspath(__file__))
MESES = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez']

# ---------------------------------------------------------------- base
from fonte import carregar_base

def carregar_incc(ini, fim):
    """Índice INCC-M acumulado por mês. O INCC de um mês sai no fim dele: os meses que ainda não
    estão em incc.json repetem o último índice conhecido e voltam em INCC_FALTA."""
    raw = json.load(open(os.path.join(PKG, 'incc.json')))['mensal_pct']
    meses = [m.strftime('%Y-%m') for m in pd.date_range(ini, fim, freq='MS')]
    falta = [m for m in meses[1:] if m not in raw]
    if falta and falta != meses[len(meses) - len(falta):]:
        sys.exit(f'INCC-M faltando em incc.json no meio do período: {", ".join(falta)}. Atualize antes de rodar.')
    INCC_FALTA[:] = falta
    idx = {}; a = 1.0
    for i, m in enumerate(meses):
        if i: a *= 1 + raw.get(m, 0) / 100
        idx[m] = a
    return idx

INCC_FALTA = []

# ---------------------------------------------------------------- geo
def dist_km(lat, lon, la0, lo0):
    p = math.pi / 180
    a = np.sin((lat - la0) * p / 2) ** 2 + np.cos(la0 * p) * np.cos(lat * p) * np.sin((lon - lo0) * p / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))

def _ccw(a, b, c): return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
def _cruza(p, q, a, b):
    return (_ccw(p, a, b) > 0) != (_ccw(q, a, b) > 0) and (_ccw(p, q, a) > 0) != (_ccw(p, q, b) > 0)

def _segmentos(geojson_path):
    path = geojson_path if os.path.isabs(geojson_path) else os.path.join(PKG, geojson_path)
    segs = []
    for f in json.load(open(path))['features']:
        g = f['geometry']; partes = [g['coordinates']] if g['type'] == 'LineString' else g['coordinates']
        if g['type'] == 'Polygon': partes = g['coordinates']
        for c in partes:
            segs += [(c[i], c[i + 1]) for i in range(len(c) - 1)]
    return segs

def _dentro(pt, anel):
    x, y = pt; dentro = False
    for i in range(len(anel) - 1):
        (x1, y1), (x2, y2) = anel[i][:2], anel[i + 1][:2]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1: dentro = not dentro
    return dentro

def estacoes():
    return json.load(open(os.path.join(PKG, 'geo', 'estacoes.json')))

def aplicar_sombras(emps, pin, sombras):
    """emps: DataFrame com lat, lon. Devolve máscara True = fica, e o texto de cada sombra."""
    fica = pd.Series(True, index=emps.index); textos = []
    for s in sombras or []:
        t = s['tipo']
        if t == 'barreira':  # sai quem está do outro lado da linha, vista do pin
            segs = _segmentos(s['geojson'])
            fora = [any(_cruza((pin['lon'], pin['lat']), (r.lon, r.lat), a, b) for a, b in segs) for r in emps.itertuples()]
            fica &= ~pd.Series(fora, index=emps.index)
            textos.append(s['descricao'] if 'descricao' in s else f"Só o lado do pin em relação a {s['nome']}")
        elif t == 'raio':  # sai quem está a até km de um ponto (ou de estações pelo nome)
            pontos = []
            if 'estacoes' in s:
                E = estacoes()
                import unicodedata
                norm = lambda z: ''.join(ch for ch in unicodedata.normalize('NFD', z.upper()) if ch.isalnum())
                for nome in s['estacoes']:
                    hit = [e for e in E if norm(e['nome']) == norm(nome)]
                    if not hit: sys.exit(f'Estação não encontrada em geo/estacoes.json: {nome}')
                    pontos += [(e['lat'], e['lon']) for e in hit]
            if 'lat' in s: pontos.append((s['lat'], s['lon']))
            for la, lo in pontos:
                fica &= dist_km(emps.lat, emps.lon, la, lo) > s['km']
            textos.append(s.get('descricao') or f"Fora de {str(s['km']).replace('.', ',')} km de {s.get('nome') or ', '.join(s.get('estacoes', []))}")
        elif t == 'poligono':  # sai quem está dentro
            path = s['geojson'] if os.path.isabs(s['geojson']) else os.path.join(PKG, s['geojson'])
            aneis = []
            for f in json.load(open(path))['features']:
                g = f['geometry']
                aneis += [g['coordinates'][0]] if g['type'] == 'Polygon' else [p[0] for p in g['coordinates']]
            dentro = [any(_dentro((r.lon, r.lat), a) for a in aneis) for r in emps.itertuples()]
            fica &= ~pd.Series(dentro, index=emps.index)
            textos.append(s.get('descricao') or f"Fora de {s['nome']}")
        else:
            sys.exit(f'Tipo de sombra desconhecido: {t}')
    return fica, textos

# ---------------------------------------------------------------- semestres
def semestres(ini, fim):
    meses = pd.date_range(ini, fim, freq='MS')
    grupos = []
    for m in meses:
        k = (m.year, 1 if m.month <= 6 else 2)
        if grupos and grupos[-1][0] == k: grupos[-1][1].append(m)
        else: grupos.append((k, [m]))
    solto = []
    if len(grupos) > 1 and len(grupos[0][1]) < 3:  # mês solto no começo: só os lançamentos dele entram no semestre seguinte
        solto = grupos[0][1]; grupos = grupos[1:]
    out = []
    for gi, ((y, h), ms) in enumerate(grupos):
        stats = ms; ms = (solto + ms) if gi == 0 else ms
        if len(stats) >= 6: lab = f'{h}S{str(y)[2:]}'
        else: lab = f'{MESES[stats[0].month-1]}–{MESES[stats[-1].month-1]} {str(y)[2:]}'
        out.append({'label': lab, 'meses': [m.strftime('%Y-%m') for m in ms], 'stats': [m.strftime('%Y-%m') for m in stats], 'n': len(stats), 'ano': str(y)})
    return out

# ---------------------------------------------------------------- cálculo
def recorte(d, bids, spec):
    tp = spec.get('tipologia', {})
    x = d[d.BID.isin(bids)]
    if tp.get('area_min') is not None: x = x[x['APRIV TIPOLOGIA'] >= tp['area_min']]
    if tp.get('area_max') is not None: x = x[x['APRIV TIPOLOGIA'] <= tp['area_max']]
    if tp.get('dorms'): x = x[x.DORMS.isin(tp['dorms'])]
    if tp.get('finalidade', 'Residencial'): x = x[x.FINALIDADE == tp.get('finalidade', 'Residencial')]
    return x

def cenario(d, bids, spec, INI, FIM, idx, SEMS):
    FAT = {k: idx[FIM.strftime('%Y-%m')] / v for k, v in idx.items()}
    x = recorte(d, bids, spec)
    t = x.sort_values(['TID', 'mes']).copy()
    t['lanc_m'] = t.lanc.dt.to_period('M').dt.to_timestamp()
    t['sold'] = (t.UTOT_TIP - t['ESTOQUE TIPOLOGIA'] > 0) | (t.Vendas_qtd > 0)
    fs = t[t.sold].groupby('BID').mes.min(); orig = t.groupby('BID').lanc_m.first()
    eff = orig.copy(); novo = orig >= INI
    if spec.get('lancamento_efetivo', True): eff[novo] = fs.reindex(orig[novo].index)
    t['L'] = t.BID.map(eff); t = t[t.L.notna()]; t = t[t.mes >= t.L].copy()
    t['novo'] = t.BID.map(novo); t['prim'] = t.groupby('TID').mes.transform('min')
    prev = t.groupby('TID')['ESTOQUE TIPOLOGIA'].shift(); ant = t['Estoque no mes anterior'].fillna(prev)
    nasce = t.novo & (t.mes == t.prim)
    t['oferta'] = np.where(nasce, t.UTOT_TIP, ant.fillna(0))
    t['pv'] = np.where(nasce, (t.UTOT_TIP - t['ESTOQUE TIPOLOGIA']).clip(lower=0), 0)
    t['vend'] = np.where(nasce, t.pv, t.Vendas_qtd - t.Distratos_qtd)
    t['idade'] = ((t.mes.dt.year - t.L.dt.year) * 12 + (t.mes.dt.month - t.L.dt.month)).clip(lower=0)
    t['faixa'] = pd.cut(t.idade, [-1, 6, 12, 24, 999], labels=['0–6', '7–12', '13–24', '25+'])
    m2s = {m: s['label'] for s in SEMS for m in s['stats']}
    t['m'] = t.mes.dt.strftime('%Y-%m'); t['sem'] = t.m.map(m2s)
    A = t['APRIV TIPOLOGIA']
    t['m2v'] = t.Vendas_qtd * A + np.where(t['PM2 Medio'].notna(), t.pv * A, 0)
    t['rsv'] = t.Venda.fillna(0) + t.pv * A * t['PM2 Medio'].fillna(0)
    t['m2e'] = np.where(t.VGV.notna(), t['ESTOQUE TIPOLOGIA'] * A, 0); t['rse'] = t.VGV.fillna(0)
    t['rsv_pres'] = t.rsv * t.m.map(FAT)
    return t

def estoque(t, INI, FIM):
    meses = pd.date_range(INI, FIM, freq='MS'); out = []
    for tid, z in t.groupby('TID'):
        U = z.UTOT_TIP.max(); s = z.set_index('mes')['ESTOQUE TIPOLOGIA'].groupby(level=0).last()
        full = s.reindex(pd.date_range(s.index.min(), FIM, freq='MS')).ffill(); full[full.index > s.index.max()] = 0
        a = full.values.astype(float)
        for i in range(1, len(a) - 1):  # neutraliza recarga de tabela de um mês só
            if a[i] - a[i - 1] > 0.3 * U and a[i + 1] < a[i] - 0.3 * U: a[i] = a[i - 1]
            elif a[i] < a[i - 1] - 0.3 * U and a[i + 1] > a[i] + 0.3 * U: a[i] = a[i - 1]
        out.append(pd.Series(a, index=full.index))
    if not out: return pd.Series(0.0, index=meses)
    return pd.concat(out, axis=1).sum(axis=1).reindex(meses).fillna(0)

def conferencia(x):
    """Unidades do Órulo × processo de licenciamento (só São Paulo, só quando a base vem do banco).
    Suspeito (Órulo acima do processo + 5%) continua no cálculo, marcado na lista (decisão do Moises, 13/nov/2026)."""
    s = x.get('conf_situacao')
    if not isinstance(s, str) or s not in ('suspeito', 'fase', 'conferido'): return {}
    return {'conf': s, 'conf_orulo': int(x.conf_unidades_orulo), 'conf_processo': int(x.conf_unidades_processo),
            'conf_proc': x.conf_processo}

def resumo(t, INI, FIM, idx, SEMS):
    L = [s['label'] for s in SEMS]; m2s = {m: s['label'] for s in SEMS for m in s['meses']}
    r = {}
    n = t[t.novo].drop_duplicates('TID'); n = n.assign(s=n.L.dt.strftime('%Y-%m').map(m2s))
    r['lanc'] = [{'sem': s, 'unid': int(n[n.s == s].UTOT_TIP.sum()), 'emps': int(n[n.s == s].BID.nunique()),
                  'nomes': [f"{e} ({int(q)} un.)" for e, q in n[n.s == s].groupby('EMP').UTOT_TIP.sum().sort_values(ascending=False).items()]} for s in L]
    est = estoque(t, INI, FIM)
    u = t[t['sem'].notna()]
    base = u.groupby('faixa', observed=True).apply(lambda z: z.vend.sum() / z.oferta.sum() if z.oferta.sum() else np.nan)
    u = u.assign(esp=u.oferta * u.faixa.map(base).astype(float))
    g = u.groupby('sem').agg(v=('vend', 'sum'), o=('oferta', 'sum'), e=('esp', 'sum'), n=('BID', 'nunique'), m2v=('m2v', 'sum'), rsv=('rsv', 'sum'))
    b = u.groupby(['sem', 'BID'])[['rse', 'm2e']].sum(); b = b[b.m2e > 0]; b['p'] = b.rse / b.m2e
    ip = [100.0]; nc = [None]
    for s0, s1 in zip(L, L[1:]):
        try: x = b.loc[s0].join(b.loc[s1], lsuffix='0', rsuffix='1', how='inner')
        except KeyError: x = pd.DataFrame()
        ip.append(ip[-1] * ((x.p1 * x.m2e0).sum() / (x.p0 * x.m2e0).sum()) if len(x) else np.nan); nc.append(len(x))
    u = u[u['sem'].notna()]
    inccsem = {s['label']: np.mean([idx[m] for m in s['stats']]) for s in SEMS}
    prev_m = (pd.Timestamp(SEMS[0]['stats'][0] + '-01') - pd.offsets.MonthBegin(1))
    r['sem'] = []
    for i, s in enumerate(SEMS):
        lab = s['label']; row = g.loc[lab] if lab in g.index else None
        fim_m = pd.Timestamp(s['meses'][-1] + '-01')
        ini_est = float(est.get(pd.Timestamp(SEMS[i - 1]['meses'][-1] + '-01'), 0)) if i else float(est.get(prev_m, 0) if prev_m in est.index else 0)
        def nz(v, f=lambda z: z): return None if row is None or pd.isna(v) else f(v)
        r['sem'].append({'sem': lab, 'emps': int(row.n) if row is not None else 0,
            'vso': nz(row.v / row.o if row is not None and row.o else np.nan, lambda z: round(z, 4)),
            'indice': nz(row.v / row.e if row is not None and row.e else np.nan, lambda z: round(z, 3)),
            'vendidas': int(round(row.v)) if row is not None else 0, 'esperadas': int(round(row.e)) if row is not None else 0,
            'oferta_mes': round(row.o / s['n'], 1) if row is not None else 0, 'vend_mes': round(row.v / s['n'], 1) if row is not None else 0,
            'estoque_fim': int(est[fim_m]), 'rs_m2_vendido': nz(row.rsv / row.m2v if row is not None and row.m2v else np.nan, round),
            'idx_mesmos': None if pd.isna(ip[i]) else round(ip[i], 1), 'n_comuns': nc[i],
            'incc_idx': round(inccsem[lab] / inccsem[L[0]] * 100, 1),
            'a_venda': int(ini_est) + r['lanc'][i]['unid']})
    # safras por ano de lançamento
    m2a = {m: s['ano'] for s in SEMS for m in s['meses']}
    a = t[t.novo].copy(); a['safra'] = a.L.dt.strftime('%Y-%m').map(m2a)
    out = []
    for tid, z in a.groupby('TID'):
        U = z.UTOT_TIP.max(); l = z.L.iloc[0]; maxk = (FIM.year - l.year) * 12 + FIM.month - l.month
        e = z.set_index('idade')['ESTOQUE TIPOLOGIA'].groupby(level=0).last(); last = e.index.max()
        full = e.reindex(range(0, maxk + 1)).ffill(); full[full.index > last] = 0
        for k, v in full.items():
            if pd.notna(v): out.append((z.safra.iloc[0], z.BID.iloc[0], tid, k, U, v))
    c = pd.DataFrame(out, columns=['safra', 'BID', 'TID', 'k', 'U', 'est'])
    SAF = sorted(c.safra.unique().tolist()) if len(c) else []
    r['safras_lista'] = SAF
    if len(c):
        cc = c.groupby(['safra', 'k']).agg(U=('U', 'sum'), est=('est', 'sum')).reset_index(); cc['vendido'] = 1 - cc.est / cc.U
        tot = c.drop_duplicates('TID').groupby('safra').U.sum(); cc['cob'] = cc.U / cc.safra.map(tot)
        cc = cc[(cc.cob >= 0.75) & (cc.k <= 24)]
    else:
        cc = pd.DataFrame(columns=['safra', 'k', 'vendido']); tot = pd.Series(dtype=float)
    r['safras'] = {s: {'emps': int(c[c.safra == s].BID.nunique()), 'unid': int(tot.get(s, 0))} for s in SAF}
    r['curvas'] = [{'s': x.safra, 'k': int(x.k), 'p': round(x.vendido, 3)} for x in cc.itertuples()]
    jan = [(3, 0, 3), (6, 4, 6), (9, 7, 9), (12, 10, 12), (18, 13, 18), (24, 19, 24)]
    tab = []
    for s in SAF:
        z = a[a.safra == s]
        for k, k0, k1 in jan:
            w = z[(z.idade >= k0) & (z.idade <= k1)]; pv = cc[(cc.safra == s) & (cc.k == k)].vendido
            ok = w.m2v.sum() > 0 and len(pv)
            tab.append({'s': s, 'idade': k, 'pct': round(float(pv.iloc[0]), 3) if len(pv) else None,
                        'rs_m2': round(w.rsv.sum() / w.m2v.sum()) if ok else None,
                        'rs_m2_hoje': round(w.rsv_pres.sum() / w.m2v.sum()) if ok else None})
    r['tabela_idade'] = tab
    r['emps'] = sorted(t.EMP.unique().tolist())
    det = []
    for bid, z in t.groupby('BID'):
        last = z[z.mes == z.mes.max()]
        det.append({'emp': z.EMP.iloc[0], 'incorp': z.INCORP.iloc[0], 'lanc': z.L.iloc[0].strftime('%m/%y') if z.novo.iloc[0] else 'antes do período',
                    'unid': int(z.drop_duplicates('TID').UTOT_TIP.sum()), 'unid_projeto': int(z.UTOT.max()),
                    'estoque': int(last['ESTOQUE TIPOLOGIA'].sum()) if z.mes.max() == FIM else 0,
                    **conferencia(z.iloc[0])})
    r['emps_det'] = sorted(det, key=lambda x: x['emp'])
    return r

# ---------------------------------------------------------------- principal
def calcular(spec, d=None):
    """Calcula o relatório da spec. Devolve (resultado, html). d: a base já carregada (o serviço guarda
    em memória); sem ela, carrega pela origem configurada (fonte.py)."""
    if d is None: d = carregar_base()
    INI, FIM = d.mes.min(), d.mes.max()
    if spec.get('periodo_inicio'): INI = max(INI, pd.Timestamp(spec['periodo_inicio'] + '-01'))
    idx = carregar_incc(INI, FIM); SEMS = semestres(INI, FIM)
    # filtros por empreendimento
    utot = d.groupby('BID').UTOT.max(); nomes = d.groupby('BID').EMP.first()
    ok = utot >= spec.get('min_unidades_projeto', 0)
    if spec.get('excluir_nr', True): ok &= ~nomes.str.contains(r'- NR\b|NR$', regex=True)
    for nm in spec.get('excluir_nomes', []): ok &= ~nomes.str.contains(nm, case=False, regex=False)
    emps = d.groupby('BID').agg(lat=('lat', 'first'), lon=('lon', 'first')).loc[ok[ok].index]
    raios = spec['raios_km']; dados = {}; meta_c = []
    for i, c in enumerate(spec['cenarios']):
        cid = c.get('id') or f'c{i+1}'
        e = emps.copy(); e['km'] = dist_km(e.lat, e.lon, c['pin']['lat'], c['pin']['lon'])
        e = e[e.km <= max(raios)]
        fica, textos = aplicar_sombras(e, c['pin'], c.get('sombras'))
        e = e[fica]
        cont = {}
        for R in raios:
            bids = e[e.km <= R].index.tolist()
            t = cenario(d, bids, spec, INI, FIM, idx, SEMS)
            dados[f'{cid}_{R}'] = resumo(t, INI, FIM, idx, SEMS); cont[str(R)] = len(dados[f'{cid}_{R}']['emps'])
            pass
        meta_c.append({'id': cid, 'nome': c['nome'], 'pin': c['pin'].get('descricao') or f"{c['pin']['lat']:.5f}, {c['pin']['lon']:.5f}",
                       'sombras': [x for x in textos if x] or ['Sem sombra'], 'n': cont})
    tp = spec.get('tipologia', {})
    faixa = f"Tipologias de {tp.get('area_min','?')} a {tp.get('area_max','?')} m² de área privativa".replace('.', ',')
    if tp.get('dorms'): faixa += f", {'/'.join(map(str, tp['dorms']))} dormitório(s)"
    exc = (['Empreendimentos NR'] if spec.get('excluir_nr', True) else []) + spec.get('excluir_nomes', [])
    if spec.get('min_unidades_projeto'): exc.append(f"empreendimentos com menos de {spec['min_unidades_projeto']} unidades no total")
    labs = [s['label'] for s in SEMS]
    sem_txt = f"{labs[0]} a {labs[-1]}" + (f"; {labs[-1]} tem {SEMS[-1]['n']} meses" if SEMS[-1]['n'] < 6 else '')
    if len(SEMS[0]['meses']) > len(SEMS[0]['stats']): sem_txt += f"; os lançamentos de {MESES[INI.month-1]}/{str(INI.year)[2:]} entram no {labs[0]}"
    per = f"{MESES[INI.month-1]}/{str(INI.year)[2:]} a {MESES[FIM.month-1]}/{str(FIM.year)[2:]}"
    meta = {'titulo': spec.get('titulo') or 'Mercado', 'subtitulo': spec.get('subtitulo') or f"{' e '.join(c['nome'] for c in spec['cenarios'])} · raios de {' e '.join(map(str, raios))} km · base Órulo, {per}",
            'periodo': per, 'gerado': datetime.date.today().strftime('%d/%m/%Y'), 'raios': raios, 'sem': labs, 'cenarios': meta_c,
            'recortes': [['Produto', faixa + ', uso ' + tp.get('finalidade', 'Residencial').lower()], ['Exclusões', ', '.join(exc) or 'Nenhuma'],
                         ['Período', f'{per}, mês a mês, por tipologia'], ['Lançamento', 'Mês da primeira venda (lançamento efetivo)' if spec.get('lancamento_efetivo', True) else 'Data de lançamento do Órulo'],
                         ['Semestres', sem_txt], ['Correção', f"INCC-M (FGV), valores trazidos a {MESES[FIM.month-1]}/{str(FIM.year)[2:]}" + (f"; sem o INCC de {', '.join(INCC_FALTA)}, ainda não publicado (mantido o último)" if INCC_FALTA else '')],
                         ['Raios', ' e '.join(map(str, raios)) + ' km do pin, em linha reta']]}
    if 'fonte' in d.columns and (d.fonte == 'monitor').any():
        m0 = d[d.fonte == 'monitor'].mes.min()
        meta['recortes'].append(['Fonte', f"Relatório de 36 meses do Órulo até {MESES[(m0 - pd.offsets.MonthBegin(1)).month-1]}/{str((m0 - pd.offsets.MonthBegin(1)).year)[2:]}; "
                                 f"de {MESES[m0.month-1]}/{str(m0.year)[2:]} em diante, coletas mensais do monitor da BKM (venda = unidade disponível que deixou de estar; "
                                 "tipologia pela mais próxima do mesmo empreendimento). Há troca de fonte nesse mês"])
    if 'conf_situacao' in d.columns:
        meta['recortes'].append(['Conferência', 'Em São Paulo, as unidades do Órulo são comparadas com o processo de licenciamento '
                                 'do lote (Aprova Digital, processos protocolados desde 2020). Acima do processo + 5% = suspeito, '
                                 'marcado na lista e mantido no cálculo'])
    res = json.loads(json.dumps({'meta': meta, 'dados': dados}, ensure_ascii=False, default=float))
    tpl = open(os.path.join(PKG, 'template.html')).read()
    html = tpl.replace('__TITULO__', meta['titulo']).replace('__DATA__', json.dumps(res, ensure_ascii=False, separators=(',', ':')))
    return res, html

def rodar(spec, saida, d=None):
    res, html = calcular(spec, d)
    os.makedirs(saida, exist_ok=True)
    json.dump(res, open(os.path.join(saida, 'resultado.json'), 'w'), ensure_ascii=False, indent=1)
    open(os.path.join(saida, 'relatorio.html'), 'w').write(html)
    print(os.path.join(saida, 'relatorio.html'))

if __name__ == '__main__':
    rodar(json.load(open(sys.argv[1])), sys.argv[2])

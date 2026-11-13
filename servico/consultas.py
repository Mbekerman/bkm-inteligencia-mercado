"""Consultas rápidas sobre a base (tipologia × mês), sem gerar relatório."""
import numpy as np, pandas as pd
from motor import dist_km


def empreendimentos(d, lat, lon, raio_km, area_min=None, area_max=None, dorms=None, finalidade='Residencial',
                    lancados_desde=None, limite=200):
    """Empreendimentos a até raio_km do ponto, com o retrato do último mês da base: estoque, vendas e VSO
    dos últimos 3 e 12 meses e R$/m² de tabela, nas tipologias do recorte."""
    x = d
    if finalidade: x = x[x.FINALIDADE == finalidade]
    if area_min is not None: x = x[x['APRIV TIPOLOGIA'] >= area_min]
    if area_max is not None: x = x[x['APRIV TIPOLOGIA'] <= area_max]
    if dorms: x = x[x.DORMS.isin(dorms)]
    e = x.groupby('BID').agg(lat=('lat', 'first'), lon=('lon', 'first'))
    e['km'] = dist_km(e.lat, e.lon, lat, lon)
    e = e[e.km <= raio_km]
    x = x[x.BID.isin(e.index)]
    fim = d.mes.max()
    out = []
    for bid, z in x.groupby('BID'):
        ult = z[z.mes == z.mes.max()]
        lanc = z.lanc.iloc[0]
        if lancados_desde and (pd.isna(lanc) or lanc < pd.Timestamp(lancados_desde)): continue
        r = {'orulo_id': int(bid), 'nome': z.EMP.iloc[-1], 'incorporadora': z.INCORP.iloc[-1],
             'municipio': z.CIDADE.iloc[-1], 'bairro': z.BAIRRO.iloc[-1], 'distancia_km': round(float(e.km[bid]), 2),
             'situacao': z.sort_values('mes').STATUS_EMP.iloc[-1],
             'lancamento': None if pd.isna(lanc) else lanc.strftime('%Y-%m'),
             'entrega': None if pd.isna(z.entr.iloc[0]) else z.entr.iloc[0].strftime('%Y-%m'),
             'unidades_projeto': None if pd.isna(z.UTOT.max()) else int(z.UTOT.max()),
             'unidades_recorte': int(z.drop_duplicates('TID').UTOT_TIP.sum()),
             'areas_m2': sorted({round(float(a), 2) for a in z['APRIV TIPOLOGIA'].dropna()}),
             'ultimo_mes': z.mes.max().strftime('%Y-%m'),
             'estoque': int(ult['ESTOQUE TIPOLOGIA'].sum()) if z.mes.max() == fim else 0}
        for n in (3, 12):
            j = z[z.mes > fim - pd.DateOffset(months=n)]
            v = float((j.Vendas_qtd.fillna(0) - j.Distratos_qtd.fillna(0)).sum())
            o = float(j['Estoque no mes anterior'].fillna(0).sum())
            r[f'vendas_{n}m'] = int(v)
            r[f'vso_mensal_{n}m'] = round(v / o, 4) if o else None
        m2 = (ult['ESTOQUE TIPOLOGIA'] * ult['APRIV TIPOLOGIA'])[ult.VGV.notna()].sum()
        r['rs_m2_tabela'] = round(float(ult.VGV.sum() / m2)) if m2 else None
        if 'conf_situacao' in z.columns and isinstance(z.conf_situacao.iloc[0], str):
            r['conferencia'] = {'situacao': z.conf_situacao.iloc[0],
                                'unidades_orulo_predio': None if pd.isna(z.conf_unidades_orulo.iloc[0]) else int(z.conf_unidades_orulo.iloc[0]),
                                'unidades_processo': None if pd.isna(z.conf_unidades_processo.iloc[0]) else int(z.conf_unidades_processo.iloc[0]),
                                'processo': z.conf_processo.iloc[0] if isinstance(z.conf_processo.iloc[0], str) else None}
        out.append(r)
    out.sort(key=lambda r: r['distancia_km'])
    return {'base_ate': fim.strftime('%Y-%m'), 'total': len(out), 'empreendimentos': out[:limite]}


def sobre_a_base(d):
    f = d.fonte.value_counts().to_dict() if 'fonte' in d.columns else {}
    return {'meses': [d.mes.min().strftime('%Y-%m'), d.mes.max().strftime('%Y-%m')],
            'empreendimentos': int(d.BID.nunique()), 'tipologias': int(d.TID.nunique()), 'linhas': len(d),
            'linhas_por_fonte': {k: int(v) for k, v in f.items()},
            'municipios': sorted(d.CIDADE.dropna().unique().tolist())}

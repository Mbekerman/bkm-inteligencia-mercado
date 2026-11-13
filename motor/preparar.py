"""Converte o relatório do Órulo (xlsx, tipologia × mês) em cache/base.pkl.

Uso: python3 preparar.py "<arquivo.xlsx>"
Lê o XML do xlsx em streaming (openpyxl seria lento para 300 mil linhas).
"""
import sys, os, re, csv, zipfile, tempfile
from xml.etree.ElementTree import iterparse
import pandas as pd
PKG = os.path.dirname(os.path.abspath(__file__))
COLS = ['BID','TID','EMP','INCORP','STATUS_EMP','TIPO_EMP','SUBTIPO','BAIRRO','CIDADE','UF','LAT','LON','UTOT','FINALIDADE',
        'DENTREGA','DLANCAMENTO','ESTOQUE TIPOLOGIA','APRIV TIPOLOGIA','DORMS','SUITES','VAGAS','VGV','PM2 Medio','Venda',
        'Vendas_qtd','Distratos_qtd','Estoque no mes anterior','UTOT_TIP','TIPOLOGIA_DATAATUALIZ_INICIO_MES','link']

def xlsx_para_csv(xlsx, csv_out):
    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    with zipfile.ZipFile(xlsx) as z:
        ss = []
        with z.open('xl/sharedStrings.xml') as f:
            for ev, el in iterparse(f):
                if el.tag == ns + 'si': ss.append(''.join(t.text or '' for t in el.iter(ns + 't'))); el.clear()
        def col(ref):
            n = 0
            for ch in re.match(r'([A-Z]+)', ref).group(1): n = n * 26 + ord(ch) - 64
            return n - 1
        w = csv.writer(open(csv_out, 'w', newline=''))
        with z.open('xl/worksheets/sheet1.xml') as f:
            for ev, el in iterparse(f):
                if el.tag == ns + 'row':
                    cells = {}
                    for c in el.findall(ns + 'c'):
                        v = c.find(ns + 'v')
                        if v is None: continue
                        cells[col(c.get('r'))] = ss[int(v.text)] if c.get('t') == 's' else v.text
                    n = max(cells) + 1 if cells else 0
                    w.writerow([cells.get(i, '') for i in range(n)]); el.clear()

def normalizar(d):
    falta = [c for c in COLS if c not in d.columns]
    if falta: sys.exit(f'Colunas que faltam no relatório: {falta}')
    d = d[COLS].copy()
    X = lambda s: pd.to_datetime(pd.to_numeric(s, errors='coerce'), unit='D', origin='1899-12-30')
    d['mes'] = X(d['TIPOLOGIA_DATAATUALIZ_INICIO_MES']).dt.to_period('M').dt.to_timestamp()
    d['lanc'] = X(d['DLANCAMENTO']); d['entr'] = X(d['DENTREGA'])
    for c in ('LAT', 'LON'): d[c.lower()] = pd.to_numeric(d[c].astype(str).str.replace(',', '.'), errors='coerce')
    d = d[d.lat.notna() & d.mes.notna()]
    return d

if __name__ == '__main__':
    xlsx = sys.argv[1]
    with tempfile.TemporaryDirectory() as tmp:
        c = os.path.join(tmp, 'base.csv'); xlsx_para_csv(xlsx, c)
        d = pd.read_csv(c, low_memory=False)
    d = normalizar(d)
    os.makedirs(os.path.join(PKG, 'cache'), exist_ok=True)
    d.to_pickle(os.path.join(PKG, 'cache', 'base.pkl'))
    print(f'{len(d)} linhas, {d.BID.nunique()} empreendimentos, {d.mes.min():%m/%Y} a {d.mes.max():%m/%Y}')

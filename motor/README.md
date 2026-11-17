# Inteligência de Mercado BKM

Gera o relatório de mercado (lançamentos; à venda, vendas e estoque; lançadas × vendidas; VSO; curvas e tabela de venda por idade do empreendimento. Preço × INCC, ajuste de preço e índice de velocidade saíram da página em 17/nov/2026 a pedido do Moises; os números continuam no resultado) a partir do relatório do Órulo (tipologia × mês).

## Arquivos
- `preparar.py "<relatorio.xlsx>"`: converte o xlsx do Órulo em `cache/base.pkl` (~1 min). Rode de novo quando chegar relatório novo.
- `motor.py <spec.json> <pasta_saida>`: calcula e grava `resultado.json` e `relatorio.html`.
- `template.html`: a página (gráficos com hover, cabeçalho BKM, tema claro/escuro).
- `incc.json`: INCC-M mensal (%). Precisa cobrir todos os meses da base menos o primeiro.
- `geo/estacoes.json`: estações de Metrô, CPTM e ViaMobilidade (GeoSampa).
- `geo/barreiras/*.json`: linhas (GeoJSON) usadas como barreira (Rio Pinheiros/Jurubatuba, canal da Guarapiranga).
- `exemplos/*.json`: specs já rodadas.

## Spec
```json
{
  "titulo": "Mercado de 28 a 33 m²",
  "tipologia": {"area_min": 28, "area_max": 33, "dorms": null, "finalidade": "Residencial"},
  "excluir_nr": true,
  "excluir_nomes": ["Moremais João Dias"],
  "min_unidades_projeto": 80,
  "raios_km": [3, 5],
  "lancamento_efetivo": true,
  "cenarios": [
    {"id": "vb", "nome": "Vila das Belezas",
     "pin": {"lat": -23.6468, "lon": -46.7376, "descricao": "R. Tomás de Sousa, 640"},
     "sombras": [
       {"tipo": "barreira", "nome": "Marginal Pinheiros", "geojson": "geo/barreiras/rio-pinheiros-jurubatuba.json"},
       {"tipo": "raio", "km": 1.5, "estacoes": ["Corinthians-Itaquera"]},
       {"tipo": "raio", "km": 1, "lat": -23.5, "lon": -46.6, "nome": "ponto X"},
       {"tipo": "poligono", "nome": "Área Y", "geojson": "geo/poligonos/area-y.json"}]}
  ]
}
```
Sombras: `barreira` tira quem fica do outro lado da linha, olhando do pin (o segmento pin → empreendimento cruza a linha); `raio` tira quem está a até `km` de um ponto ou de estações (nome como em `geo/estacoes.json`, sem diferença de acento, espaço ou hífen); `poligono` tira quem está dentro. `descricao` muda o texto mostrado; `"descricao": ""` esconde.

## Regras de cálculo (decididas com o Moises, nov/2026)
- Recorte por tipologia (área privativa, dormitórios), uso residencial; exclui nomes com "- NR"; exclui empreendimentos com menos de `min_unidades_projeto` unidades no TOTAL do projeto (todas as tipologias), não do estoque nem da faixa.
- Lançamento efetivo = mês da primeira venda. Lançados antes do primeiro mês da base são estoque (fora das safras).
- Semestres: 1S/2S; o último parcial vira "jul–out 26"; mês solto no começo (dez/23) só soma lançamentos ao primeiro semestre.
- Estoque corrigido (decisão do Moises, 13/nov/2026): o Órulo às vezes zera ou recarrega a tabela de um empreendimento e grava isso como vendas e distratos falsos (ex.: Vivaz Ermelino Matarazzo 1 e 2 em 2025). Por tipologia, a série mensal do estoque (mês sem linha repete o anterior) é corrigida: **recarga** = o estoque sobe mais de 30% das unidades da tipologia e desce de novo (mais de 30%) em até 2 meses; **zeramento** = cai mais de 30% (ou vai a zero) e volta (sobe mais de 30%, ou, depois de ir a zero, volta a pelo menos metade do que era) em até 2 meses. Nesses meses o estoque fica o de antes do salto, sem venda nem distrato; o mês da volta fica com a diferença real.
- Vendas líquidas = estoque corrigido do mês anterior − estoque corrigido (o estoque fecha por construção), não vendas − distratos do Órulo; no mês de nascimento da tipologia, a pré-venda é unidades − estoque. O R$/m² vendido usa as vendas do Órulo limitadas às vendas líquidas do mês (recarga não vira venda com preço).
- À venda no semestre = estoque inicial + lançadas + entradas (tipologia que aparece no meio da base num empreendimento já lançado, ou que nasce com estoque acima das unidades); estoque no fim = à venda − vendidas − saídas (tipologia que some da base com estoque). `nao_fecha` de cada semestre tem de dar 0. Lançadas contam no semestre em que a tipologia nasce.
- Linhas do Órulo que não fecham (estoque anterior − vendas + distratos ≠ estoque, diferença acima de 5% das unidades do projeto) e os meses neutralizados ficam marcados na lista de empreendimentos (`nao_fecha`, `recargas`). As safras e o índice de preço usam o estoque corrigido.
- VSO = Σ vendas ÷ Σ oferta, mês a mês. Índice = vendas ÷ esperadas pelo VSO de cada faixa de idade (0–6, 7–12, 13–24, 25+) do próprio cenário.
- Preço nominal = R$/m² médio das vendidas; ajuste % = índice encadeado dos mesmos empreendimentos (R$/m² de tabela do estoque); INCC-M médio do semestre.
- Sem informação de venda (decisão do Moises, 17/nov/2026): empreendimento que está na base há 6 meses ou mais e, no último mês em que aparece, tem estoque igual ao total de unidades (todas as tipologias) sai do relatório inteiro e é listado em Exclusões. Ex.: Sol Connection Mooca, 326 de 326 em estoque desde jun/25.
- Safras por ano de lançamento; curva e tabela por idade do empreendimento até 24 meses. Em cada idade entram todos os empreendimentos da safra que já chegaram nela (sem corte de cobertura desde 17/nov/2026, decisão do Moises; lançados há menos de 3 meses do fim da base ficam fora da safra; antes só aparecia com ≥ 75% das unidades da safra); `n` = empreendimentos no ponto, `cob` = fração das unidades da safra.

## Mapa (17/nov/2026)
Cada cenário leva em `meta.cenarios[].geo` o pin, os raios, a geometria das sombras (linhas das barreiras, círculos
de exclusão, polígonos) e as estações até 1 km além do maior raio. A seção "Mapa" do template desenha isso no
Google Maps com a chave que o app de relatórios injeta (`window.BKM_MAPS_KEY`); shoppings e hipermercados vêm da
API Places na hora de abrir a página (só redes de hiper e atacarejo, dentro do maior raio). Sem chave (link direto
do serviço de mercado) a seção mostra um aviso. `window.__mapaPronto` vira `true` quando os mapas terminam, e o
PDF do app espera por ele.

"""Serviço de inteligência de mercado da BKM: API HTTP e servidor MCP sobre o mesmo motor.

Variáveis de ambiente:
- DATABASE_URL: conexão Postgres com o usuário im_leitor (só leitura), vinda do Secret Manager.
- CHAVES: JSON {"cliente": "<sha256 da chave em hex>"}. Cada cliente (Claude, Grok...) tem a sua chave,
  mandada em Authorization: Bearer <chave>. Guardar só o hash; trocar uma chave = trocar o hash.
- BUCKET: bucket do Cloud Storage onde ficam os relatórios gerados (sem ele, ficam na memória).
- BASE_HORAS: de quantas em quantas horas a base é relida do banco (padrão 6).
- URL_PUBLICA: endereço do serviço, para montar o link dos relatórios.

Rotas: GET /saude (aberta), GET /base, GET /empreendimentos, POST /relatorio, GET /relatorios/<id>
(aberta: o id é o segredo do link), GET /regras, POST /sql, GET /esquema, GET /unidades/<orulo_id>,
GET /processos, e o MCP em /mcp (as mesmas consultas como ferramentas).
"""
import os, sys, json, time, uuid, hashlib, hmac, threading, contextlib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'motor'))
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
import fonte, motor, consultas, banco

RAIZ = os.path.dirname(os.path.abspath(__file__))
REGRAS = open(os.path.join(RAIZ, '..', 'motor', 'README.md')).read()


# ---------------------------------------------------------------- base em memória
class Base:
    def __init__(self, horas):
        self.d = None; self.em = 0; self.horas = horas; self.trava = threading.Lock()

    def get(self):
        with self.trava:
            if self.d is None or time.time() - self.em > self.horas * 3600:
                self.d = fonte.carregar_base(); self.em = time.time()
            return self.d


BASE = Base(float(os.environ.get('BASE_HORAS', 6)))


# ---------------------------------------------------------------- relatórios guardados
class Guarda:
    def __init__(self, bucket):
        self.mem = {}; self.b = None
        if bucket:
            from google.cloud import storage
            self.b = storage.Client().bucket(bucket)

    def pôr(self, html, res):
        rid = uuid.uuid4().hex
        if self.b:
            self.b.blob(f'relatorios/{rid}.html').upload_from_string(html, content_type='text/html; charset=utf-8')
            self.b.blob(f'relatorios/{rid}.json').upload_from_string(json.dumps(res, ensure_ascii=False), content_type='application/json')
        else:
            self.mem[rid] = html
        return rid

    def tirar(self, rid):
        if not rid.isalnum() or len(rid) != 32: return None
        if self.b:
            bl = self.b.blob(f'relatorios/{rid}.html')
            return bl.download_as_text() if bl.exists() else None
        return self.mem.get(rid)


GUARDA = Guarda(os.environ.get('BUCKET'))


def link(rid):
    return f"{os.environ.get('URL_PUBLICA', '').rstrip('/')}/relatorios/{rid}"


# ---------------------------------------------------------------- chaves
def _chaves():
    try: return json.loads(os.environ.get('CHAVES', '{}'))
    except ValueError: return {}


def _chaves_do_pedido(req):
    """Candidatas a chave: Authorization (com ou sem "Bearer ") e X-API-Key. Vale a que conferir: alguns
    clientes (o conector do claude.ai) põem o próprio Authorization e a nossa chave vai no X-API-Key."""
    out = []
    for h in ('x-api-key', 'authorization'):
        a = (req.headers.get(h) or '').strip()
        if a.lower().startswith('bearer '): a = a[7:].strip()
        if a: out.append(a)
    return out


def cliente(chave):
    if not chave: return None
    h = hashlib.sha256(chave.encode()).hexdigest()
    for nome, hh in _chaves().items():
        if hmac.compare_digest(h, hh): return nome
    return None


# ---------------------------------------------------------------- funções comuns à API e ao MCP
def gerar_relatorio(spec):
    """spec no formato de motor/README.md. Devolve o link do relatório e um resumo por cenário e raio."""
    if not spec.get('cenarios') or not spec.get('raios_km'):
        raise ValueError('A spec precisa de cenarios (com pin) e raios_km.')
    res, html = motor.calcular(spec, BASE.get())
    rid = GUARDA.pôr(html, res)
    resumo = {}
    for k, v in res['dados'].items():
        resumo[k] = {'empreendimentos': len(v['emps']),
                     'semestres': [{s['sem']: {'vso_mensal': s['vso'], 'vendidas': s['vendidas'], 'estoque_fim': s['estoque_fim'],
                                               'rs_m2_vendido': s['rs_m2_vendido'], 'lancadas': l['unid']}}
                                   for s, l in zip(v['sem'], v['lanc'])],
                     'suspeitos': [e['emp'] for e in v['emps_det'] if e.get('conf') == 'suspeito']}
    return {'id': rid, 'link': link(rid), 'meta': res['meta'], 'resumo': resumo}


# ---------------------------------------------------------------- MCP
# sem a proteção contra DNS rebinding, que só aceita Host localhost (é para servidor local; aqui protege a chave)
mcp = FastMCP('bkm-inteligencia-mercado', stateless_http=True, json_response=True, streamable_http_path='/',
              transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))


@mcp.tool()
def base_de_dados() -> dict:
    """Período, quantidade de empreendimentos e tipologias e municípios da base do Órulo (São Paulo e
    região metropolitana; relatório de 36 meses até out/2026 e coletas mensais do monitor da BKM depois)."""
    return consultas.sobre_a_base(BASE.get())


@mcp.tool()
def buscar_empreendimentos(lat: float, lon: float, raio_km: float = 3, area_min: float | None = None,
                           area_max: float | None = None, dormitorios: list[int] | None = None,
                           lancados_desde: str | None = None, limite: int = 100) -> dict:
    """Empreendimentos a até raio_km (linha reta) de um ponto, com estoque, vendas e VSO mensal dos últimos 3 e
    12 meses e R$/m² de tabela, nas tipologias da faixa de área e dormitórios pedida. lancados_desde: 'AAAA-MM'.
    Em São Paulo vem a conferência das unidades com o processo de licenciamento (suspeito = Órulo acima do processo)."""
    return consultas.empreendimentos(BASE.get(), lat, lon, raio_km, area_min, area_max, dormitorios, 'Residencial',
                                     lancados_desde, limite)


@mcp.tool()
def relatorio_de_mercado(spec: dict) -> dict:
    """Gera o relatório de mercado (lançamentos, vendas, estoque, preço × INCC, VSO, índice de velocidade,
    curvas por safra) e devolve o link da página e um resumo. Leia antes as regras (ferramenta regras_do_relatorio):
    spec = {titulo, tipologia: {area_min, area_max, dorms, finalidade}, excluir_nr, excluir_nomes,
    min_unidades_projeto, raios_km: [3, 5], lancamento_efetivo, cenarios: [{id, nome, pin: {lat, lon, descricao},
    sombras: [...]}]}."""
    return gerar_relatorio(spec)


@mcp.tool()
def regras_do_relatorio() -> str:
    """Formato da spec do relatório, tipos de sombra e as regras de cálculo decididas pela BKM."""
    return REGRAS


@mcp.tool()
def esquema_do_banco() -> list:
    """Tabelas e views do monitor de mercado (im_*) com colunas, tipos e descrições. Leia antes de consulta_sql."""
    return banco.esquema()


@mcp.tool()
def consulta_sql(sql: str, limite: int = 1000) -> dict:
    """Consulta SQL livre, só de leitura, no banco do monitor (Postgres; tabelas public.im_*). Um comando por vez,
    até 60 s e até `limite` linhas (máx. 5000). Devolve {colunas, linhas, total, cortado}. Para conhecer as
    tabelas, use esquema_do_banco. Unidades: im_unidades + im_unidade_estados (ate_coleta_id nulo = estado atual);
    empreendimento pelo id do Órulo: im_ids_externos (entidade 'empreendimento', fonte 'orulo%')."""
    return banco.consulta_livre(sql, limite)


@mcp.tool()
def tabela_de_unidades(orulo_id: int, incluir_removidas: bool = False) -> dict:
    """Cabeçalho do empreendimento (pelo id do Órulo) e todas as unidades: torre, andar, número, tipo, dormitórios,
    vagas, área, situação e preço atuais, R$/m², primeiro preço, grupo (tipologia do resumo) e venda."""
    return banco.unidades(orulo_id, incluir_removidas)


@mcp.tool()
def processos_licenciamento(orulo_id: int | None = None, lote: str | None = None, texto: str | None = None,
                            desde: str | None = None, min_unidades: int | None = None, social: bool | None = None,
                            limite: int = 200) -> dict:
    """Processos de edificação nova do Aprova Digital (São Paulo). orulo_id: os do prédio do empreendimento.
    lote: setor+quadra+lote (10 dígitos). texto: parte do endereço ou do assunto, ou o número do processo.
    desde: 'AAAA-MM-DD' (autuação). social: HIS/HMP/R2V. Sem filtro, os mais recentes."""
    return banco.processos(orulo_id, lote, texto, desde, min_unidades, social, limite)


# ---------------------------------------------------------------- HTTP
mcp_app = mcp.streamable_http_app()


@contextlib.asynccontextmanager
async def vida(app):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title='BKM Inteligência de Mercado', lifespan=vida)
ABERTAS = ('/saude', '/relatorios/')


@app.middleware('http')
async def autenticar(req: Request, prox):
    if not req.url.path.startswith(ABERTAS):
        cands = _chaves_do_pedido(req)
        quem = next((q for q in map(cliente, cands) if q), None)
        chave = cands[0] if cands else ''
        if not quem:
            # diagnóstico sem expor a chave: se veio, de que jeito e com quantos caracteres
            print(json.dumps({'severity': 'WARNING', 'auth': 'recusada', 'caminho': req.url.path,
                              'cabecalhos': sorted(k for k in req.headers.keys() if k in ('authorization', 'x-api-key')),
                              'bearer': (req.headers.get('authorization') or '').lower().startswith('bearer '),
                              'tamanho': len(chave), 'prefixo_bkm': chave.startswith('bkm_')}), flush=True)
            return JSONResponse({'erro': 'chave inválida ou ausente (Authorization: Bearer <chave>)'}, 401)
        req.state.cliente = quem
    return await prox(req)


@app.get('/saude')
def saude():
    return {'ok': True, 'base_carregada': BASE.d is not None}


@app.get('/base')
def base():
    return consultas.sobre_a_base(BASE.get())


@app.get('/empreendimentos')
def rota_empreendimentos(lat: float, lon: float, raio_km: float = 3, area_min: float | None = None,
                         area_max: float | None = None, dormitorios: list[int] | None = Query(None),
                         lancados_desde: str | None = None, limite: int = 100):
    return consultas.empreendimentos(BASE.get(), lat, lon, raio_km, area_min, area_max, dormitorios, 'Residencial',
                                     lancados_desde, limite)


@app.post('/relatorio')
def rota_relatorio(spec: dict):
    try: return gerar_relatorio(spec)
    except (ValueError, KeyError) as e: raise HTTPException(400, str(e))


@app.get('/relatorios/{rid}', response_class=HTMLResponse)
def rota_ver(rid: str):
    html = GUARDA.tirar(rid)
    if html is None: raise HTTPException(404, 'relatório não encontrado')
    return html


@app.get('/regras', response_class=HTMLResponse)
def rota_regras():
    return '<pre>' + REGRAS.replace('&', '&amp;').replace('<', '&lt;') + '</pre>'


@app.post('/sql')
def rota_sql(corpo: dict):
    try: return banco.consulta_livre(corpo.get('sql', ''), corpo.get('limite', 1000))
    except ValueError as e: raise HTTPException(400, str(e))
    except Exception as e: raise HTTPException(400, f'{type(e).__name__}: {e}')


@app.get('/esquema')
def rota_esquema():
    return banco.esquema()


@app.get('/unidades/{orulo_id}')
def rota_unidades(orulo_id: int, incluir_removidas: bool = False):
    try: return banco.unidades(orulo_id, incluir_removidas)
    except ValueError as e: raise HTTPException(404, str(e))


@app.get('/processos')
def rota_processos(orulo_id: int | None = None, lote: str | None = None, texto: str | None = None,
                   desde: str | None = None, min_unidades: int | None = None, social: bool | None = None,
                   limite: int = 200):
    try: return banco.processos(orulo_id, lote, texto, desde, min_unidades, social, limite)
    except ValueError as e: raise HTTPException(404, str(e))


app.mount('/mcp', mcp_app)


# ---------------------------------------------------------------- chave no endereço
# O conector do claude.ai não manda cabeçalho próprio (só OAuth): para ele a chave vai no caminho,
# .../k/<chave>/mcp/. Vira o mesmo "Authorization: Bearer <chave>" antes de tudo. Os outros clientes
# continuam com o cabeçalho, que não aparece nos logs de acesso; o caminho aparece (ver docs/deploy.md).
_api = app


async def app(scope, receive, send):
    if scope['type'] == 'http' and scope['path'].startswith('/k/'):
        resto = scope['path'][3:]
        chave, _, caminho = resto.partition('/')
        caminho = '/' + caminho
        scope = dict(scope, path=caminho, raw_path=caminho.encode(),
                     headers=[(k, v) for k, v in scope['headers'] if k != b'authorization']
                     + [(b'authorization', f'Bearer {chave}'.encode())])
    # /mcp sem a barra: o Starlette redirecionaria para http://.../mcp/ (atrás do Cloud Run perde o https)
    # e o POST do cliente não segue; o claude.ai tira a barra do fim do endereço.
    if scope['type'] == 'http' and scope['path'] == '/mcp':
        scope = dict(scope, path='/mcp/', raw_path=b'/mcp/')
    await _api(scope, receive, send)

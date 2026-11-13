# Deploy do serviço (Cloud Run)

Projeto do Google Cloud `bkm-terrenos`, região `southamerica-east1`, serviço `inteligencia-mercado`.
Os comandos rodam no Cloud Shell, dentro de um clone deste repositório.

## 1. Usuário só de leitura no banco (uma vez)
Depois do PR do monitor que cria o papel `im_leitor` estar aplicado, no SQL Editor do Supabase, com uma senha forte gerada por você:
```sql
alter role im_leitor login password '<senha>';
```
A conexão usa o **Session pooler** do Supabase (o Cloud Run não fala IPv6, que a conexão direta exige). Em Connect › Session pooler, copie a URI e troque o usuário `postgres.<ref>` por `im_leitor.<ref>` e a senha pela de cima:
`postgresql://im_leitor.mghqcsycuurjezoiiyfp:<senha>@<host do pooler>:5432/postgres`

## 2. Segredos e bucket (uma vez)
```bash
gcloud config set project bkm-terrenos
printf '%s' 'postgresql://im_leitor.mghqcsycuurjezoiiyfp:<senha>@<host>:5432/postgres' | gcloud secrets create im-database-url --data-file=-
python3 servico/nova_chave.py claude     # mostra a chave do cliente e a linha do JSON
python3 servico/nova_chave.py grok
printf '%s' '{"claude": "<hash>", "grok": "<hash>"}' | gcloud secrets create im-chaves --data-file=-
gcloud storage buckets create gs://bkm-inteligencia-relatorios --location=southamerica-east1 --uniform-bucket-level-access
SA=$(gcloud projects describe bkm-terrenos --format='value(projectNumber)')-compute@developer.gserviceaccount.com
for s in im-database-url im-chaves; do gcloud secrets add-iam-policy-binding $s --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor; done
gcloud storage buckets add-iam-policy-binding gs://bkm-inteligencia-relatorios --member=serviceAccount:$SA --role=roles/storage.objectAdmin
```
Cliente novo ou chave vazada: gere outra com `nova_chave.py`, troque o JSON (`gcloud secrets versions add im-chaves --data-file=-`) e faça um deploy de novo.

## 3. Deploy
```bash
gcloud run deploy inteligencia-mercado --source . --region southamerica-east1 \
  --memory 2Gi --cpu 1 --timeout 600 --min-instances 0 --max-instances 2 --allow-unauthenticated \
  --set-secrets DATABASE_URL=im-database-url:latest,CHAVES=im-chaves:latest \
  --set-env-vars BUCKET=bkm-inteligencia-relatorios,BASE_HORAS=6
URL=$(gcloud run services describe inteligencia-mercado --region southamerica-east1 --format='value(status.url)')
gcloud run services update inteligencia-mercado --region southamerica-east1 --update-env-vars URL_PUBLICA=$URL
curl $URL/saude
```
`--allow-unauthenticated` porque quem protege é a chave de cada cliente (o Grok e outros agentes não falam o login do Google). Sem chave, só `/saude` e o link de um relatório (o id de 32 caracteres é o segredo do link) respondem.

A primeira chamada depois de o serviço dormir lê a base inteira do banco (cerca de 20 s); depois fica em memória por `BASE_HORAS`.

## 4. Conectar um agente
- MCP (Claude, Grok, outros): endereço `<URL>/mcp/`, transporte Streamable HTTP, cabeçalho `Authorization: Bearer <chave>`.
- HTTP: `GET <URL>/empreendimentos?lat=..&lon=..&raio_km=3&area_min=28&area_max=33`, `POST <URL>/relatorio` com a spec (ver `motor/README.md`), sempre com o mesmo cabeçalho.

## Redeploy depois de um merge

```bash
cd ~/bkm-inteligencia-mercado && git pull
gcloud run deploy inteligencia-mercado --source . --region southamerica-east1
```
Só isso: mantém segredos, bucket e URL_PUBLICA. Não repetir o comando do primeiro deploy (o `--set-env-vars` apaga o URL_PUBLICA).

## Conector no claude.ai

O conector personalizado do claude.ai não manda cabeçalho próprio, então a chave vai no endereço:
`https://inteligencia-mercado-469931692112.southamerica-east1.run.app/k/<chave>/mcp/`.
O serviço troca `/k/<chave>` pelo cabeçalho `Authorization: Bearer <chave>`. Atenção: o caminho aparece
nos logs de requisição do Cloud Run; quem lê os logs do projeto vê essa chave. Usar uma chave só para o
claude.ai, para poder trocá-la sozinha. Os demais clientes (Grok, scripts) usam o cabeçalho.

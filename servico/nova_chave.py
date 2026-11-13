"""Gera a chave de um cliente novo do serviço (Claude, Grok...).

Uso: python3 servico/nova_chave.py <nome-do-cliente>
Mostra a chave (entregar ao cliente, uma vez) e a linha para o JSON da variável CHAVES (só o hash).
"""
import sys, secrets, hashlib, json
nome = sys.argv[1] if len(sys.argv) > 1 else sys.exit(__doc__)
chave = 'bkm_' + secrets.token_urlsafe(32)
print('Chave (entregue ao cliente e não guarde):', chave)
print('Para CHAVES:', json.dumps({nome: hashlib.sha256(chave.encode()).hexdigest()}))

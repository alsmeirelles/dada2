"""
Gera uma API_KEY criptograficamente segura para uso no .env.

Uso:
    python gen_key.py
"""

import secrets

key = secrets.token_hex(32)
print(f"API_KEY={key}")
print()
print("Cole a linha acima no seu arquivo .env")
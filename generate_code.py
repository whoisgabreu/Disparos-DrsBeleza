import base64
import hashlib
import re


def gerar_codigo(telefone: str, palavra_chave: str, tamanho: int = 8) -> str:
    # Limpa o telefone deixando apenas números e normaliza a palavra-chave
    tel_limpo = re.sub(r"\D", "", telefone)
    chave_limpa = palavra_chave.strip().lower()

    # Combina os dados de entrada
    entrada = f"{tel_limpo}:{chave_limpa}".encode("utf-8")

    # Gera um hash SHA-256 e converte para caracteres alfanuméricos maiúsculos (A-Z, 2-7)
    digest = hashlib.sha256(entrada).digest()
    codigo_base32 = base64.b32encode(digest).decode("utf-8")

    return f"cód.+{codigo_base32[:tamanho]}"


if __name__ == "__main__":
    # --- Exemplo de uso ---
    telefone = "(31) 99999-8888"
    palavra = "promo2026"

    print(gerar_codigo(telefone, palavra))
    # Saída exemplo: cód.+K7M2P9XQ

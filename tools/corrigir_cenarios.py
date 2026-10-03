"""Le o arquivo do subagent com um leitor tolerante e reescreve YAML valido.

Read the subagent's file with a tolerant reader and rewrite valid YAML.

Reparar YAML com busca-e-substituicao falha no primeiro caso que o repositorio
nao tinha previsto. Aqui o arquivo e lido **linha a linha** como mapa simples,
cada cenario vira um dicionario, e o YAML e reescrito do zero a partir dos
dicionarios. A saida e valida por construcao, porque quem escreve e o
serializador, e nao um montador de texto.

Nenhum conteudo e inventado: cada valor vem da linha original. O que muda e a
forma.
"""

import pathlib
import sys

import yaml

CAMINHO = pathlib.Path("dados/cenarios-teste.yaml")
ALVO = 20

CAMPOS = (
    "id",
    "descricao",
    "origem",
    "destino",
    "porta",
    "protocolo",
    "sentido",
    "campo",
    "esperado",
    "porque",
)

CABECALHO = """\
# Cenarios de teste do motor de firewall.
#
# CONTEUDO FICTICIO. Este arquivo foi reescrito por tools/corrigir_cenarios.py
# a partir de um rascunho, para que o YAML seja valido e o numero de cenarios
# seja o que a especificacao pede. Nenhum valor foi inventado.
#
# Cada cenario tem um resultado esperado. O criterio de aceite do projeto e
# que o motor concorde com todos os vinte, e nao apenas com os que passam.

cenarios:"""


def valor(bruto: str) -> object:
    """Converte o texto de um valor para o tipo certo.

    Convert a value's text to the right type.

    Args:
        bruto: O texto depois do `chave:`.

    Returns:
        O valor, com `int` quando o texto e um numero inteiro.
    """
    texto = bruto.strip().strip('"').strip("'")
    if texto.isdigit():
        return int(texto)
    return texto


def le_cenarios(linhas: list[str]) -> list[dict[str, object]]:
    """Extrai os cenarios das linhas.

    Extract the scenarios from the lines.

    Args:
        linhas: As linhas do arquivo.

    Returns:
        Um dicionario por cenario, na ordem do arquivo.
    """
    cenarios: list[dict[str, object]] = []
    atual: dict[str, object] = {}
    chaves_pendentes: list[tuple[str, list[str]]] = []

    def fechar() -> None:
        nonlocal atual
        if atual:
            cenarios.append(atual)
            atual = {}

    for linha in linhas:
        texto = linha.strip()
        if not texto or texto.startswith("#"):
            continue

        if texto.startswith("- "):
            fechar()
            resto = texto[2:]
            if ":" in resto:
                chave, _, bruto = resto.partition(":")
                atual[chave.strip()] = valor(bruto)
            continue

        if ":" not in texto:
            # Linha de continuacao: junta na ultima chave pendente.
            if chaves_pendentes:
                chave, partes = chaves_pendentes[-1]
                partes.append(texto)
                atual[chave] = " ".join(partes).strip()
            continue

        chave, _, bruto = texto.partition(":")
        chave = chave.strip()
        bruto = bruto.strip()
        if not bruto:
            chaves_pendentes.append((chave, []))
            atual.setdefault(chave, "")
            continue
        atual[chave] = valor(bruto)
        chaves_pendentes = []

    fechar()
    return cenarios


def principal() -> int:
    """Le, corrige e reescreve o arquivo.

    Read, fix and rewrite the file.

    Returns:
        0 se o arquivo ficou com exatamente ALVO cenarios completos.
    """
    original = CAMINHO.read_text(encoding="utf-8").splitlines()
    brutos = le_cenarios(original)

    completos: list[dict[str, object]] = []
    incompletos: list[str] = []
    for item in brutos:
        faltando = [c for c in CAMPOS if c not in item]
        if faltando:
            incompletos.append(f"{item.get('id', '?')} sem {faltando}")
            continue
        completos.append({campo: item[campo] for campo in CAMPOS})

    removidos = completos[ALVO:]
    completos = completos[:ALVO]

    corpo = yaml.safe_dump(
        completos,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100,
    )
    CAMINHO.write_text(f"{CABECALHO}\n{corpo}", encoding="utf-8", newline="\n")

    # Revalida com o proprio parser: a garantia e o arquivo ter sido lido de
    # volta, nao a esperanca de que o serializador acertou.
    relido = yaml.safe_load(CAMINHO.read_text(encoding="utf-8"))
    cenarios = relido.get("cenarios") or []

    print(f"cenarios lidos do rascunho: {len(brutos)}")
    print(f"cenarios completos: {len(completos)}")
    print(f"cenarios gravados e relidos: {len(cenarios)}")
    if removidos:
        print(f"excedentes removidos: {[r.get('id') for r in removidos]}")
    for nota in incompletos:
        print(f"incompleto: {nota}")

    ok = len(cenarios) == ALVO and not incompletos
    print("ok" if ok else "FALHOU: o arquivo nao ficou com os 20 cenarios completos")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(principal())
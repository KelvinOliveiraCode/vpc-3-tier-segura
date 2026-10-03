"""A linha de comando do vpcsim.

The vpcsim command line.

Quatro comandos:

- `tracar` - roda os cenarios de um YAML e mostra o caminho de cada pacote.
- `cenarios` - lista os cenarios com o resultado que o motor deu.
- `regras` - mostra a tabela de regras, na ordem em que o motor avalia.
- `arquitetura` - mostra as camadas, os nos e as rotas.

O codigo de saida de `tracar` e `cenarios` e **1 quando algum cenario diverge
do esperado**. E o que torna o comando usavel como portao: um job que roda os
vinte cenarios e falha quando o motor passa a discordar do esperado.

## Por que o tracador e o produto

Um motor que so responde "permitido" ou "bloqueado" e um programa de prova
d'evidencia: o resultado esta certo e a causa e opaca. Quem opera nao tem como
saber se um bloqueio e uma regra que nao funciona, uma rota que falta, ou uma
regra nao esperada.

Por isso o tracador mostra o caminho inteiro - origem, destino, rota, e a
regra que decidiu - e o `exemplos/tracos-de-trafego.txt` vai para o repositorio
para ser lido sem instalar nada.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import cenarios as modulo_cenarios
from . import rede as modulo_rede
from . import regras as modulo_regras
from .cenarios import BLOQUEADO, PERMITIDO, Cenario

SAIDA_OK = 0
SAIDA_DIVERGENTE = 1
SAIDA_ERRO = 2

ARQUITETURA_PADRAO = "dados/arquitetura.yaml"
REGRAS_PADRAO = "dados/regras.yaml"
CENARIOS_PADRAO = "dados/cenarios-teste.yaml"


class ErroDeUso(Exception):
    """O comando foi chamado com argumentos que nao fazem sentido."""


def _constroi_parser() -> argparse.ArgumentParser:
    """Monta o parser de argumentos.

    Build the argument parser.

    Returns:
        O parser pronto.
    """
    parser = argparse.ArgumentParser(
        prog="vpcsim",
        description=(
            "Simulador local de VPC com motor de firewall. Nenhuma nuvem real "
            "e acessada. / Local VPC simulator with a firewall engine."
        ),
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p_tracar = sub.add_parser(
        "tracar",
        help="roda os cenarios e mostra o caminho de cada pacote",
        description="Roda os cenarios e imprime o tracado de cada pacote.",
    )
    p_tracar.add_argument("cenarios", nargs="?", default=CENARIOS_PADRAO)
    p_tracar.add_argument("--arquitetura", default=ARQUITETURA_PADRAO)
    p_tracar.add_argument("--regras", default=REGRAS_PADRAO)
    p_tracar.add_argument("--saida", help="grava os tracos neste arquivo")
    p_tracar.add_argument(
        "--somente-divergentes",
        action="store_true",
        help="imprime so o cenario cujo resultado divergiu",
    )

    p_cenarios = sub.add_parser(
        "cenarios",
        help="lista os cenarios e o veredito de cada um",
        description="Lista os cenarios com o resultado que o motor deu.",
    )
    p_cenarios.add_argument("cenarios", nargs="?", default=CENARIOS_PADRAO)
    p_cenarios.add_argument("--arquitetura", default=ARQUITETURA_PADRAO)
    p_cenarios.add_argument("--regras", default=REGRAS_PADRAO)

    p_regras = sub.add_parser(
        "regras",
        help="mostra a tabela de regras na ordem de avaliacao",
        description="Mostra as regras na ordem em que o motor as avalia.",
    )
    p_regras.add_argument("regras", nargs="?", default=REGRAS_PADRAO)

    p_arq = sub.add_parser(
        "arquitetura",
        help="mostra as camadas, os nos e as rotas",
        description="Mostra a arquitetura carregada.",
    )
    p_arq.add_argument("arquitetura", nargs="?", default=ARQUITETURA_PADRAO)

    return parser


def _estado(cenario: Cenario) -> frozenset[tuple[str, str]]:
    """O conjunto de conexoes ja autorizadas de um cenario.

    The set of already-authorized connections of a scenario.

    O par e acrescentado **nas duas direcoes**, porque o motor procura o par
    em qualquer sentido: a resposta de uma conexao permitida e o mesmo par
    visto do outro lado. Guardar so uma direcao faria a resposta cair na
    avaliacao normal e ser bloqueada por uma regra que existe para proteger a
    ida, que e o erro classico de firewall stateless.

    Args:
        cenario: O cenario.

    Returns:
        O conjunto de pares autorizados, nos dois sentidos.
    """
    pares: set[tuple[str, str]] = set()
    for origem, destino in cenario.estabelecidas:
        pares.add((origem, destino))
        pares.add((destino, origem))
    return frozenset(pares)


def _conexao_de(cenario: Cenario):
    """A conexao do motor para um cenario.

    The engine's connection for a scenario.

    O `campo` tem de vir do cenario. Sem ele, todo pacote entra como `novo` e
    o motor nunca chega a etapa de trafego de retorno - o caminho mais
    importante do motor fica morto, e o cenario de resposta diverge sem que
    nada esteja errado.

    Args:
        cenario: O cenario.

    Returns:
        A conexao, com o campo de estado definido.
    """
    from .firewall import Conexao

    return Conexao.com_campo(
        cenario.campo,
        origem=cenario.origem,
        destino=cenario.destino,
        porta=cenario.porta,
        protocolo=cenario.protocolo,
        sentido=cenario.sentido,
        id=cenario.id,
    )


def _veredito(decisao) -> str:
    """O veredito em uma palavra.

    The verdict in one word.

    Args:
        decisao: A decisao do motor.

    Returns:
        `PERMITIDO` ou `BLOQUEADO`.
    """
    return PERMITIDO if decisao.permitida else BLOQUEADO


def _cmd_tracar(args: argparse.Namespace, destino) -> int:
    """Executa `tracar`.

    Run `tracar`.

    Args:
        args: Os argumentos.
        destino: Onde imprimir.

    Returns:
        0 se todos os cenarios bateram, 1 se algum divergiu, 2 em erro.
    """
    from .tracador import formatar, tracar

    arquitetura = modulo_rede.carregar(args.arquitetura)
    tabela = modulo_regras.carregar(args.regras)
    casos = modulo_cenarios.carregar(args.cenarios)

    linhas: list[str] = [
        "=" * 78,
        f"TRACOS DE TRAFEGO - {len(casos)} cenario(s)",
        f"arquitetura: {arquitetura.nome}   regras: {len(tabela)}",
        "=" * 78,
        "",
    ]

    divergentes: list[str] = []
    for caso in casos:
        conexao = _conexao_de(caso)

        traco = tracar(
            conexao,
            tabela,
            arquitetura,
            conexoes_estabelecidas=_estado(caso),
        )
        obtido = _veredito(traco.decisao)
        if obtido != caso.esperado:
            divergentes.append(caso.id)

        if args.somente_divergentes and obtido == caso.esperado:
            continue

        linhas.append(formatar(traco))
        marca = "ok" if obtido == caso.esperado else "DIVERGIU"
        linhas.append(f"resultado esperado: {caso.esperado}   obtido: {obtido}   [{marca}]")
        if caso.porque:
            linhas.append(f"porque: {caso.porque}")
        linhas.append("")

    texto = "\n".join(linhas)
    print(texto, file=destino)

    if args.saida:
        caminho = Path(args.saida)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(texto + "\n", encoding="utf-8", newline="\n")
        print(f"tracos gravados em {caminho}", file=destino)

    print("=" * 78, file=destino)
    if divergentes:
        print(
            f"{len(divergentes)} cenario(s) divergiram do esperado: "
            f"{', '.join(divergentes)}",
            file=destino,
        )
        return SAIDA_DIVERGENTE

    print(f"todos os {len(casos)} cenarios concordam com o motor", file=destino)
    return SAIDA_OK


def _cmd_cenarios(args: argparse.Namespace, destino) -> int:
    """Executa `cenarios`.

    Run `cenarios`.

    Args:
        args: Os argumentos.
        destino: Onde imprimir.

    Returns:
        0 se todos bateram, 1 se algum divergiu, 2 em erro.
    """
    from .firewall import Conexao, avaliar

    arquitetura = modulo_rede.carregar(args.arquitetura)
    tabela = modulo_regras.carregar(args.regras)
    casos = modulo_cenarios.carregar(args.cenarios)

    print(f"{'cenario':<46} {'esperado':<11} {'obtido':<11} veredito", file=destino)
    print("-" * 78, file=destino)

    divergentes = 0
    for caso in casos:
        conexao = _conexao_de(caso)
        decisao = avaliar(
            conexao, tabela, arquitetura,
            conexoes_estabelecidas=_estado(caso),
        )
        obtido = _veredito(decisao)
        ok = obtido == caso.esperado
        if not ok:
            divergentes += 1
        print(
            f"{caso.id:<46} {caso.esperado:<11} {obtido:<11} "
            f"{'ok' if ok else 'DIVERGIU'}",
            file=destino,
        )

    print("-" * 78, file=destino)
    if divergentes:
        print(f"{divergentes} de {len(casos)} divergiram", file=destino)
        return SAIDA_DIVERGENTE
    print(f"todos os {len(casos)} cenarios concordam com o motor", file=destino)
    return SAIDA_OK


def _cmd_regras(args: argparse.Namespace, destino) -> int:
    """Executa `regras`.

    Run `regras`.

    Args:
        args: Os argumentos.
        destino: Onde imprimir.

    Returns:
        Sempre 0.
    """
    tabela = modulo_regras.carregar(args.regras)
    print(f"{len(tabela)} regra(s), na ordem em que o motor avalia:", file=destino)
    print("a primeira que casa decide, e a ordem faz parte da politica", file=destino)
    print("", file=destino)
    for posicao, regra in enumerate(tabela.regras, start=1):
        print(f"{posicao:>3}. {regra}", file=destino)
        if regra.motivo:
            print(f"     motivo: {regra.motivo}", file=destino)
    return SAIDA_OK


def _cmd_arquitetura(args: argparse.Namespace, destino) -> int:
    """Executa `arquitetura`.

    Run `arquitetura`.

    Args:
        args: Os argumentos.
        destino: Onde imprimir.

    Returns:
        Sempre 0.
    """
    arquitetura = modulo_rede.carregar(args.arquitetura)
    print(f"VPC: {arquitetura.nome}", file=destino)
    print("", file=destino)

    for camada, subs in arquitetura.iter_camadas():
        print(f"[{camada.upper()}]", file=destino)
        for sub in subs:
            print(
                f"  {sub.nome:<18} {sub.cidr:<18} {sub.visibilidade}",
                file=destino,
            )
            for no in arquitetura.nos:
                if no.sub_rede == sub.nome:
                    print(
                        f"    {no.nome:<22} {no.endereco:<16} papel={no.papel}",
                        file=destino,
                    )
        print("", file=destino)

    print("[ROTAS]", file=destino)
    for rota in arquitetura.rotas:
        proximo = rota.proximo or "direto"
        print(
            f"  {rota.origem:<18} -> {rota.destino:<18} via {proximo}",
            file=destino,
        )
    return SAIDA_OK


def main(argv: list[str] | None = None) -> int:
    """O ponto de entrada.

    The entry point.

    Args:
        argv: Os argumentos, sem `argv[0]`. `None` usa `sys.argv`.

    Returns:
        O codigo de saida do processo.
    """
    parser = _constroi_parser()
    args = parser.parse_args(argv)

    acoes = {
        "tracar": _cmd_tracar,
        "cenarios": _cmd_cenarios,
        "regras": _cmd_regras,
        "arquitetura": _cmd_arquitetura,
    }
    acao = acoes.get(args.comando)
    if acao is None:
        parser.error(f"comando desconhecido: {args.comando}")
        return SAIDA_ERRO

    try:
        return acao(args, sys.stdout)
    except (modulo_rede.ErroDeArquitetura,
            modulo_regras.ErroDeRegra,
            modulo_cenarios.ErroDeCenario) as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return SAIDA_ERRO
    except ErroDeUso as erro:
        print(f"uso invalido: {erro}", file=sys.stderr)
        return SAIDA_ERRO
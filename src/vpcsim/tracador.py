"""Modulo de rastreamento de pacotes na VPC simulada.

Shows the path of a packet and which rule the decision was taken.
"""

from __future__ import annotations

from dataclasses import dataclass

from .firewall import Conexao, Decisao, avaliar
from .rede import Arquitetura


@dataclass(frozen=True)
class Passo:
    """Um passo no rastreamento de um pacote.

    A step in packet tracing.

    Attributes:
        etapa: Nome da etapa ('origem', 'destino', 'rota', 'avaliacao', 'regra').
        detalhe: Detalhe da etapa.
    """

    etapa: str
    detalhe: str


@dataclass(frozen=True)
class Traco:
    """O rastreamento completo de um pacote por uma decisao de firewall.

    The complete tracing of a packet through a firewall decision.

    Attributes:
        id: Identificador unico do cenario.
        conexao: A conexao original.
        decisao: A decisao de firewall tomada.
        passos: Lista ordenada de passos do rastreamento.
    """

    id: str
    conexao: Conexao
    decisao: Decisao
    passos: tuple[Passo, ...]


def _lado(fallback: str, endereco: str, arquitetura: Arquitetura) -> str:
    """Descreve um lado da conexao: no, ou endereco anonimo.

    Describe one side of the connection: the node, or the anonymous
    address.

    Args:
        fallback: O texto quando nao ha no com esse nome, como 'origem anonima'.
        endereco: O valor de conexao.origem ou conexao.destino.
        arquitetura: A VPC onde procurar o no.

    Returns:
        O texto do lado.
    """
    no = arquitetura.no_por_endereco(endereco)
    if no is None:
        return f"{fallback}: {endereco}"
    return f"{no.nome}, {no.endereco}, sub-rede {no.sub_rede}"


def tracar(
    conexao: Conexao,
    tabela,
    arquitetura: Arquitetura,
    conexoes_estabelecidas: frozenset | None = None,
) -> Traco:
    """Rastreia o caminho de um pacote ate a decisao do firewall.

    Traces the path of a packet through the network and firewall rules.

    Args:
        conexao: A conexao a ser rastreada.
        tabela: A tabela de regras de firewall.
        arquitetura: A arquitetura da rede.
        conexoes_estabelecidas: Conexoes ja autorizadas (opcional).

    Returns:
        O rastreamento completo do pacote.
    """
    # Etapa 1: origem
    origem = _lado("origem anonima", conexao.origem, arquitetura)

    # Etapa 2: destino
    destino = _lado("destino anonima", conexao.destino, arquitetura)

    # Etapa 3: rota
    rota = arquitetura.rota_para(conexao.destino, origem=conexao.origem)
    if rota is None:
        rota_texto = f"nenhuma rota alcanca {conexao.destino}; e aqui que o pacote morre"
    else:
        proximo = rota.proximo if rota.proximo is not None else "direto"
        rota_texto = f"rota {rota.origem} -> {rota.destino}, proximo salto {proximo}"

    # Etapa 4: avaliacao
    decisao = avaliar(conexao, tabela, arquitetura, conexoes_estabelecidas)
    motivo = decisao.motivo if decisao.motivo else "sem motivo registrado"
    avaliacao_texto = f"etapa {decisao.etapa}: {motivo}"

    # Etapa 5: regra
    if decisao.regra is not None:
        regra_texto = str(decisao.regra)
    else:
        regra_texto = "nenhuma regra casou"

    # Montar tuplo de passos (ordem especificada pelo usuario)
    passos = (
        Passo(etapa="origem", detalhe=origem),
        Passo(etapa="destino", detalhe=destino),
        Passo(etapa="rota", detalhe=rota_texto),
        Passo(etapa="avaliacao", detalhe=avaliacao_texto),
        Passo(etapa="regra", detalhe=regra_texto),
    )

    # Gerar id baseado no id da conexao
    id_traco = conexao.id

    return Traco(
        id=id_traco,
        conexao=conexao,
        decisao=decisao,
        passos=passos,
    )


def formatar(traco: Traco) -> str:
    """Formata um rastreamento para exibicao humana.

    Formats a tracing result for human readable display.

    Args:
        traco: O rastreamento a ser formatado.

    Returns:
        Texto formatado com o caminho e o veredicto.
    """
    linhas: list[str] = []

    # Linha de id e origem/destino com seta
    linhas.append(f"[{traco.id}] {traco.conexao.origem} -> {traco.conexao.destino}")

    # Linhas de passos (indentadas)
    for passo in traco.passos:
        indentado = f"  {passo.etapa}: {passo.detalhe}"
        linhas.append(indentado)

    # Ultima linha: VEREDITO
    veredicto = "PERMITIDO" if traco.decisao.permitida else "BLOQUEADO"
    linhas.append(f"VEREDITO: {veredicto}")

    return "\n".join(linhas)
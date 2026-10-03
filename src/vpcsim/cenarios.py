"""Carrega os cenarios de teste do YAML.

Load the test scenarios from YAML.

Separado do CLI e do tracador porque os cenarios sao **dado de teste**, e
dado de teste tem uma exigencia que codigo nao tem: o resultado esperado faz
parte do arquivo.

Um cenario sem `esperado` e um teste que passa por accident, e um teste que
passa por accident e pior do que um teste que nao existe - ele da a mesma
sensacao de seguranca sem dar nenhuma.

## O campo `estabelecidas`

Cenarios de trafego de resposta precisam saber qual conexao foi permitida
antes. Isso nao cabe no cenario sozinho, porque e estado **entre** cenarios,
e nao propriedade de um.

Por isso a chave `estabelecidas` fica no cenario: a lista de pares
`origem-destino` que o motor deve considerar ja autorizadas. O CLI monta o
`frozenset` a partir dela e passa ao motor. E assim o estado continua visivel
no arquivo, no estado global de um teste anterior que ninguem consegue
rastrear.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Campos obrigatorios de um cenario.
CAMPOS = ("id", "origem", "destino", "porta", "protocolo", "sentido", "esperado")

# Valores aceitos no campo `esperado`.
PERMITIDO = "permitido"
BLOQUEADO = "bloqueado"


class ErroDeCenario(Exception):
    """O arquivo de cenarios esta invalido.

    The scenario file is invalid.
    """


@dataclass(frozen=True)
class Cenario:
    """Um caso de teste do motor.

    One test case of the engine.

    Attributes:
        id: Identificador unico.
        origem: Endereco de origem.
        destino: Endereco de destino.
        porta: Porta de destino.
        protocolo: `tcp` ou `udp`.
        sentido: `entrada` ou `saida`.
        campo: `novo`, `relacionado` ou `estabelecido`.
        esperado: `PERMITIDO` ou `BLOQUEADO`.
        descricao: O que o cenario representa.
        porque: Por que o resultado esperado e o correto.
        estabelecidas: Pares ja autorizados, para o trafego de resposta.
    """

    id: str
    origem: str
    destino: str
    porta: int
    protocolo: str
    sentido: str
    esperado: str
    campo: str = "novo"
    descricao: str = ""
    porque: str = ""
    estabelecidas: tuple[tuple[str, str], ...] = ()

    @property
    def par(self) -> tuple[str, str]:
        """O par de enderecos do cenario.

        The scenario's address pair.
        """
        return (self.origem, self.destino)


def _par_de_estabelecidas(bruto: Any) -> tuple[tuple[str, str], ...]:
    """Converte a lista de pares autorizados.

    Convert the list of authorized pairs.

    Args:
        bruto: O valor cru do YAML.

    Returns:
        Os pares, como tuplas de dois enderecos.

    Raises:
        ErroDeCenario: Se algum item nao tiver os dois enderecos.
    """
    if bruto is None:
        return ()
    if not isinstance(bruto, list):
        raise ErroDeCenario("estabelecidas: esperado uma lista de pares")

    pares: list[tuple[str, str]] = []
    for indice, item in enumerate(bruto):
        if not isinstance(item, dict):
            raise ErroDeCenario(f"estabelecidas[{indice}]: esperado um mapa")
        try:
            origem = str(item["origem"])
            destino = str(item["destino"])
            ipaddress.ip_address(origem)
            ipaddress.ip_address(destino)
        except KeyError as erro:
            raise ErroDeCenario(
                f"estabelecidas[{indice}]: falta a chave {erro}"
            ) from None
        except ValueError as erro:
            raise ErroDeCenario(
                f"estabelecidas[{indice}]: endereco invalido ({erro})"
            ) from None
        pares.append((origem, destino))
    return tuple(pares)


def de_documento(documento: dict[str, Any], origem: str = "") -> tuple[Cenario, ...]:
    """Constroi os cenarios a partir de um documento ja lido.

    Build the scenarios from an already-read document.

    Args:
        documento: O mapa do YAML.
        origem: O arquivo, usado nos erros.

    Returns:
        Os cenarios, na ordem do arquivo.

    Raises:
        ErroDeCenario: Se algum cenario estiver incompleto ou invalido.
    """
    if not isinstance(documento, dict):
        raise ErroDeCenario("o arquivo precisa ser um mapa no topo", origem)

    itens = documento.get("cenarios")
    if not isinstance(itens, list):
        raise ErroDeCenario(
            "cenarios: esperado uma lista no topo, com a chave 'cenarios'", origem
        )

    problemas: list[str] = []
    cenarios: list[Cenario] = []
    vistos: set[str] = set()

    for indice, item in enumerate(itens):
        onde = f"cenarios[{indice}]"
        if not isinstance(item, dict):
            problemas.append(f"{onde}: esperado um mapa")
            continue

        faltando = [c for c in CAMPOS if item.get(c) in (None, "")]
        if faltando:
            problemas.append(f"{onde}: falta {', '.join(faltando)}")
            continue

        identificador = str(item["id"])
        if identificador in vistos:
            problemas.append(f"{onde}: id {identificador!r} repetido")
            continue
        vistos.add(identificador)

        esperado = str(item["esperado"]).strip().lower()
        if esperado not in (PERMITIDO, BLOQUEADO):
            problemas.append(
                f"{onde}.esperado: {esperado!r} invalido; use "
                f"'{PERMITIDO}' ou '{BLOQUEADO}'"
            )
            continue

        try:
            porta = int(item["porta"])
            if not 1 <= porta <= 65535:
                raise ValueError("fora de 1..65535")
        except (TypeError, ValueError) as erro:
            problemas.append(f"{onde}.porta: {erro}")
            continue

        try:
            ipaddress.ip_address(str(item["origem"]))
            ipaddress.ip_address(str(item["destino"]))
        except ValueError as erro:
            problemas.append(f"{onde}: endereco invalido ({erro})")
            continue

        try:
            estabelecidas = _par_de_estabelecidas(item.get("estabelecidas"))
        except ErroDeCenario as erro:
            problemas.append(f"{onde}: {erro}")
            continue

        cenarios.append(
            Cenario(
                id=identificador,
                origem=str(item["origem"]),
                destino=str(item["destino"]),
                porta=porta,
                protocolo=str(item["protocolo"]).strip().lower(),
                sentido=str(item["sentido"]).strip().lower(),
                esperado=esperado,
                campo=str(item.get("campo", "novo")).strip().lower(),
                descricao=str(item.get("descricao", "")),
                porque=str(item.get("porque", "")),
                estabelecidas=estabelecidas,
            )
        )

    if problemas:
        raise ErroDeCenario("; ".join(problemas), origem)

    return tuple(cenarios)


def carregar(caminho: str | Path) -> tuple[Cenario, ...]:
    """Le os cenarios de um YAML.

    Read the scenarios from a YAML.

    Args:
        caminho: O arquivo.

    Returns:
        Os cenarios validados, na ordem do arquivo.

    Raises:
        ErroDeCenario: Se o arquivo nao existir ou nao passar na validacao.
    """
    import yaml

    caminho = Path(caminho)
    if not caminho.exists():
        raise ErroDeCenario(f"arquivo nao encontrado: {caminho}", str(caminho))

    try:
        documento = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as erro:
        raise ErroDeCenario(f"YAML invalido: {erro}", str(caminho)) from None

    return de_documento(documento, str(caminho))
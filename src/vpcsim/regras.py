"""As regras de seguranca, e a ordem em que sao avaliadas.

The security rules, and the order they are evaluated in.

Uma regra tem **sentido** - entrada ou saida. Isso nao e detalhe de sintaxe:
e a metade da pergunta. "A internet alcanca a aplicacao na 443" e "a aplicacao
sai para a internet na 443" sao as duas metades de uma conversa, e uma regra
que responde as duas e uma regra que nao protege nada.

## Primeira regra que casa vence

A tabela e avaliada **de cima para baixo** e a primeira regra que casa decide.
Isso e o mesmo modelo do netfilter e das ACLs de rede em geral, e e uma
escolha com consequencia: **a ordem no arquivo e parte da politica de
seguranca**.

A consequencia pratica e que duas regras que se contradizem nao sao um erro, e
uma politica: a primeira vence. Um arquivo com `permitir` antes de `negar`
deixa passar tudo, e isso e intencional - quem escreve a regra sabe o que esta
escrevendo. O que nao e aceitavel e a intencao sem documentacao, e por isso
todo regra aqui carrega `motivo`.

A alternativa seria juntar as regras e negar por padrao. Perde a ordem, e a
ordem e o que permite dizer "esta regra existe para nao bloquear o
    monitoramento" sem que a logica fique espalhada pelo arquivo.

## Campo de estado e trafego de retorno

Uma conexao de ida tem uma resposta, e a resposta nao passa por regra nova:
ela volta pela mesma conexao, no mesmo estado.

Tratar a resposta como um pacote novo e o erro classico. Ele produz duas
consequencias ruins ao mesmo tempo:

1. a resposta e bloqueada, e a conexao que a regra de ida permitiu morre;
2. para consertar, alguem acrescenta uma regra de "resposta", e essa regra
    permite mais do que a intencao original.

Por isso `Campo` tem tres valores, e o de retorno so vale quando ha uma regra
de ida na mesma tabela que permitiu a ida:

| campo | o que significa |
|---|---|
| `novo` | primeira vez que se ve esse par |
| `relacionado` | resposta a uma conexao ja permitida |
| `estabelecido` | trafego que a conexao ja permitida gerou |

O motor e **stateful**: sem regra de ida, nao ha regra de resposta, e o
`relacionado` cai para `novo` e segue a avaliacao normal.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

# Sentido da regra: o que a regra filtra.
ENTRADA = "entrada"
SAIDA = "saida"
SENTIDOS = (ENTRADA, SAIDA)

# Acao da regra.
PERMITIR = "permitir"
NEGAR = "negar"
ACOES = (PERMITIR, NEGAR)

# Campo de estado do pacote.
NOVO = "novo"
RELACIONADO = "relacionado"
ESTABELECIDO = "estabelecido"
CAMPOS = (NOVO, RELACIONADO, ESTABELECIDO)

# Protocolos que o laboratorio conhece.
TCP = "tcp"
UDP = "udp"
QUALQUER = "qualquer"
PROTOCOLOS = (TCP, UDP, QUALQUER)

# Casa com qualquer porta, usada quando a regra nao restringe.
QUALQUER_PORTA = 0


class ErroDeRegra(Exception):
    """A regra ou a tabela de regras e invalida.

    The rule or the rule table is invalid.
    """


def _ip(valor: object) -> ipaddress.IPv4Network:
    """Converte texto em faixa, aceitando IP solto.

    Convert text into a range, accepting a bare IP.

    Um arquivo de regra escreve `192.168.10.0/24` mais vezes do que
    `192.168.10.5`, mas escrever `/32` a mao e ruido. Aceitar as duas formas
    evita que o autor invente sintaxe para expressar "este host".

    Args:
        valor: O texto do YAML.

    Returns:
        A faixa correspondente.

    Raises:
        ErroDeRegra: Se o texto nao for um endereco.
    """
    texto = str(valor).strip()
    if "/" not in texto:
        texto = f"{texto}/32"
    try:
        return ipaddress.ip_network(texto, strict=False)
    except ValueError as erro:
        raise ErroDeRegra(f"endereco invalido {valor!r} ({erro})") from None


@dataclass(frozen=True)
class Regra:
    """Uma regra de seguranca.

    A security rule.

    Attributes:
        identificador: Nome estavel, como `dmz-app-443`. Aparece no tracador,
            e um tracador que diz "regra 7" obriga o leitor a abrir o arquivo.
        sentido: `ENTRADA` ou `SAIDA`.
        origem: Faixa de origem, em notacao CIDR.
        destino: Faixa de destino.
        portas: Portas de destino permitidas. Vazio significa qualquer porta.
        protocolo: `TCP`, `UDP` ou `QUALQUER`.
        acao: `PERMITIR` ou `NEGAR`.
        campo: `NOVO`, `RELACIONADO` ou `ESTABELECIDO`.
        motivo: Por que a regra existe. O tracador imprime.
    """

    identificador: str
    sentido: str
    origem: str
    destino: str
    portas: tuple[int, ...] = ()
    protocolo: str = TCP
    acao: str = PERMITIR
    campo: str = NOVO
    motivo: str = ""

    def __post_init__(self) -> None:
        if self.sentido not in SENTIDOS:
            raise ErroDeRegra(
                f"regra {self.identificador!r}: sentido {self.sentido!r} "
                f"desconhecido; use {SENTIDOS}"
            )
        if self.acao not in ACOES:
            raise ErroDeRegra(
                f"regra {self.identificador!r}: acao {self.acao!r} desconhecida"
            )
        if self.protocolo not in PROTOCOLOS:
            raise ErroDeRegra(
                f"regra {self.identificador!r}: protocolo {self.protocolo!r} "
                "desconhecido"
            )
        if self.campo not in CAMPOS:
            raise ErroDeRegra(
                f"regra {self.identificador!r}: campo {self.campo!r} desconhecido"
            )
        if not self.identificador.strip():
            raise ErroDeRegra("regra sem identificador")
        for porta in self.portas:
            if not 1 <= porta <= 65535:
                raise ErroDeRegra(
                    f"regra {self.identificador!r}: porta {porta} fora de 1..65535"
                )

    @property
    def rede_origem(self) -> ipaddress.IPv4Network:
        """A faixa de origem como objeto."""
        return _ip(self.origem)

    @property
    def rede_destino(self) -> ipaddress.IPv4Network:
        """A faixa de destino como objeto."""
        return _ip(self.destino)

    def casa(
        self,
        sentido: str,
        origem: str,
        destino: str,
        porta: int,
        protocolo: str,
        campo: str,
    ) -> bool:
        """Se o trafego casa com a regra.

        Whether the traffic matches the rule.

        Todos os criterios precisam casar. E "todos" e o ponto: uma regra que
        casa por "qualquer um dos criterios" e uma regra que permite demais,
        e nao uma regra flexivel.

        Args:
            sentido: `ENTRADA` ou `SAIDA`.
            origem: Endereco de origem.
            destino: Endereco de destino.
            porta: Porta de destino.
            protocolo: `tcp` ou `udp`.
            campo: O campo de estado do pacote.

        Returns:
            Verdadeiro se todos os criterios casarem.
        """
        if self.sentido != sentido:
            return False
        # `campo` e o criterio que faz a regra ser de ida ou de resposta. Uma
        # regra de `novo` nao casa com trafego de resposta, e e isso que
        # impede o response de reabrir a discussao.
        if self.campo != campo:
            return False
        if self.protocolo not in (QUALQUER, protocolo):
            return False
        try:
            origem_ip = ipaddress.ip_address(origem)
            destino_ip = ipaddress.ip_address(destino)
        except ValueError:
            return False
        if origem_ip not in self.rede_origem:
            return False
        if destino_ip not in self.rede_destino:
            return False
        if self.portas and porta not in self.portas:
            return False
        return True

    def para_dict(self) -> dict[str, object]:
        """A regra como dicionario, para JSON.

        The rule as a dictionary, for JSON.
        """
        return {
            "id": self.identificador,
            "sentido": self.sentido,
            "origem": self.origem,
            "destino": self.destino,
            "portas": list(self.portas),
            "protocolo": self.protocolo,
            "acao": self.acao,
            "campo": self.campo,
            "motivo": self.motivo,
        }

    def __str__(self) -> str:
        """A regra em uma linha, para o tracador.

        The rule on one line, for the tracer.
        """
        portas = (
            ",".join(str(p) for p in self.portas) if self.portas else "qualquer"
        )
        return (
            f"{self.acao} {self.sentido} "
            f"{self.origem} -> {self.destino}:{portas}/{self.protocolo} "
            f"[{self.campo}] #{self.identificador}"
        )


@dataclass(frozen=True)
class TabelaDeRegras:
    """Uma tabela ordenada de regras.

    An ordered table of rules.

    A ordem e a do arquivo, e ela **e** a politica: a primeira regra que casa
    decide. Ver a docstring do modulo.

    Attributes:
        regras: As regras, na ordem de avaliacao.
    """

    regras: tuple[Regra, ...] = ()

    def __len__(self) -> int:
        """Quantas regras a tabela tem.

        How many rules the table has.

        Returns:
            O numero de regras.
        """
        return len(self.regras)

    def por_sentido(self, sentido: str) -> tuple[Regra, ...]:
        """As regras de um sentido, na ordem.

        The rules of one direction, in order.

        Args:
            sentido: `ENTRADA` ou `SAIDA`.

        Returns:
            As regras desse sentido, na ordem de avaliacao.
        """
        return tuple(r for r in self.regras if r.sentido == sentido)

    def por_identificador(self, identificador: str) -> Regra | None:
        """Ache uma regra pelo identificador.

        Find a rule by identifier.

        Args:
            identificador: O identificador da regra.

        Returns:
            A regra, ou `None`.
        """
        for regra in self.regras:
            if regra.identificador == identificador:
                return regra
        return None

    def validar(self) -> None:
        """Checa a coerencia da tabela.

        Check the table's coherence.

        Raises:
            ErroDeRegra: Se houver identificador repetido.
        """
        vistos: set[str] = set()
        problemas: list[str] = []
        for regra in self.regras:
            if regra.identificador in vistos:
                problemas.append(f"regra {regra.identificador!r} declarada duas vezes")
            vistos.add(regra.identificador)
        if problemas:
            raise ErroDeRegra("; ".join(problemas))


def de_documento(
    documento: dict[str, object],
    origem: str = "",
) -> TabelaDeRegras:
    """Constroi a tabela a partir de um documento ja lido.

    Build the table from an already-read document.

    Args:
        documento: O mapa do YAML.
        origem: O arquivo, usado nos erros.

    Returns:
        A tabela validada, na ordem do documento.

    Raises:
        ErroDeRegra: Se alguma regra for invalida ou a tabela for incoerente.
    """
    if not isinstance(documento, dict):
        raise ErroDeRegra("o arquivo precisa ser um mapa no topo", origem)

    itens = documento.get("regras") or []
    if not isinstance(itens, list):
        raise ErroDeRegra("regras: esperado uma lista", origem)

    problemas: list[str] = []
    regras: list[Regra] = []
    for indice, item in enumerate(itens):
        onde = f"regras[{indice}]"
        if not isinstance(item, dict):
            problemas.append(f"{onde}: esperado um mapa")
            continue
        try:
            portas = item.get("portas") or []
            if isinstance(portas, (int, str)):
                portas = [portas]
            regras.append(
                Regra(
                    identificador=str(item.get("id", "")),
                    sentido=str(item.get("sentido", ENTRADA)).strip().lower(),
                    origem=str(item.get("origem", "")),
                    destino=str(item.get("destino", "")),
                    portas=tuple(int(p) for p in portas),
                    protocolo=str(item.get("protocolo", TCP)).strip().lower(),
                    acao=str(item.get("acao", PERMITIR)).strip().lower(),
                    campo=str(item.get("campo", NOVO)).strip().lower(),
                    motivo=str(item.get("motivo", "")),
                )
            )
        except (ErroDeRegra, TypeError, ValueError) as erro:
            problemas.append(f"{onde}: {erro}")

    if problemas:
        raise ErroDeRegra("; ".join(problemas), origem)

    tabela = TabelaDeRegras(regras=tuple(regras))
    try:
        tabela.validar()
    except ErroDeRegra as erro:
        raise ErroDeRegra(str(erro), origem) from None
    return tabela


def carregar(caminho: str | Path) -> TabelaDeRegras:
    """Le a tabela de regras de um YAML.

    Read the rule table from a YAML.

    Args:
        caminho: O arquivo.

    Returns:
        A tabela validada.

    Raises:
        ErroDeRegra: Se o arquivo nao existir ou nao passar na validacao.
    """
    import yaml

    caminho = Path(caminho)
    if not caminho.exists():
        raise ErroDeRegra(f"arquivo nao encontrado: {caminho}", str(caminho))

    try:
        documento = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as erro:
        raise ErroDeRegra(f"YAML invalido: {erro}", str(caminho)) from None

    return de_documento(documento, str(caminho))

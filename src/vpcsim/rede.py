"""O modelo de rede da VPC simulada.

The network model of the simulated VPC.

Uma VPC de tres camadas, com sub-redes, tabelas de roteamento e os nos que
existem entre elas. Este modulo **descreve**; nao decide nada sobre trafego.
A decisao e do `firewall.py`, e a rastreabilidade e do `tracador.py`.

A separacao importa e e a mesma do projeto vizinho: um modelo que tambem
decide vira um modelo em que nobody consegue dizer *por que* o trafego passou.
Aqui o modelo so sabe o que existe.

## Tres camadas, e por que a ordem importa

DMZ, aplicacao e dados. A ordem **e** a seguranca:

```
        internet
            |
     +------v------+
     |     DMZ     |   balancer e servidores publicos
     +------+------+
            |
     +------v------+
     |   APLICACAO  |   servidores de aplicacao, sem acesso direto
     +------+------+
            |
     +------v------+
     |    DADOS    |   banco. So a camada de aplicacao chega aqui
     +-------------+
```

A propriedade que a arquitetura quer e simples de enunciar e dificil de
garantir: **o banco nao aceita conexao vinda da internet**. Todo o resto do
desenho existe para tornar essa frase verdadeira em vez de desejada.

## Sub-rede publica e privada

`publica` e `privada` nao sao adjetivos, sao o **caminho** do pacote. Uma
sub-rede publica tem rota de retorno para a internet; uma privada nao. Sem
isso, "internet" seria so um rotulo e o motor nao teria como recusar acesso
direto ao banco sem uma regra.

O endereco `203.0.113.0/24` e o bloco de documentacao da RFC 5737, reservado
para texto e exemplo. Ele nunca aparece em rota real, e essa e a razao de ele
poder aparecer aqui.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Sequence

# Camadas, da mais exposta para a mais interna. A ordem e a do arquivo YAML e
# a ordem em que o tracador apresenta.
CAMPOS_DA_CAMADA = ("dmz", "aplicacao", "dados", "gerencia")

# visibilidade de uma sub-rede.
PUBLICA = "publica"
PRIVADA = "privada"
VISIBILIDADES = (PUBLICA, PRIVADA)

# O bloco reservado a documentacao pela RFC 5737. Um endereco de internet aqui
# e sempre ficticio, e o laboratorio insiste nisso.
REDE_INTERNET = ipaddress.ip_network("203.0.113.0/24")


class ErroDeArquitetura(Exception):
    """O YAML descreve uma arquitetura que o modelo nao aceita.

    The YAML describes an architecture the model does not accept.
    """

    def __init__(self, problemas: Sequence[str], origem: str = "") -> None:
        self.problemas = tuple(problemas)
        self.origem = origem
        sufixo = f" em {origem}" if origem else ""
        super().__init__(f"arquitetura invalida{sufixo}: {'; '.join(self.problemas)}")


@dataclass(frozen=True)
class SubRede:
    """Uma sub-rede da VPC.

    A subnet of the VPC.

    Attributes:
        nome: Identificador unico, como `dmz-publica`.
        cidr: A faixa, em notacao CIDR.
        camada: Uma de `CAMPOS_DA_CAMADA`.
        visibilidade: `PUBLICA` ou `PRIVADA`.
    """

    nome: str
    cidr: str
    camada: str
    visibilidade: str = PRIVADA

    def __post_init__(self) -> None:
        if self.camada not in CAMPOS_DA_CAMADA:
            raise ErroDeArquitetura(
                [f"sub-rede {self.nome!r}: camada {self.camada!r} desconhecida"]
            )
        if self.visibilidade not in VISIBILIDADES:
            raise ErroDeArquitetura(
                [
                    f"sub-rede {self.nome!r}: visibilidade "
                    f"{self.visibilidade!r} desconhecida"
                ]
            )
        try:
            ipaddress.ip_network(self.cidr, strict=True)
        except ValueError as erro:
            raise ErroDeArquitetura(
                [f"sub-rede {self.nome!r}: CIDR invalido {self.cidr!r} ({erro})"]
            ) from None

    @property
    def rede(self) -> ipaddress.IPv4Network:
        """A faixa como objeto.

        The range as an object.
        """
        return ipaddress.ip_network(self.cidr)

    @property
    def gateway(self) -> str:
        """O primeiro endereco da faixa.

        The first address of the range.
        """
        return str(self.rede.network_address + 1)

    def contem(self, endereco: str) -> bool:
        """Se um endereco esta nesta sub-rede.

        Whether an address is in this subnet.

        Args:
            endereco: O endereco a testar.

        Returns:
            Verdadeiro se o endereco pertence a faixa.
        """
        try:
            return ipaddress.ip_address(endereco) in self.rede
        except ValueError:
            return False

    def validar(self, problemas: list[str]) -> None:
        """Acumula os problemas deste objeto.

        Collect this object's problems.

        Args:
            problemas: Lista onde os problemas sao acumulados.
        """
        if not self.nome.strip():
            problemas.append("sub-rede sem nome")


@dataclass(frozen=True)
class No:
    """Uma maquina dentro da VPC.

    A machine inside the VPC.

    Attributes:
        nome: Identificador, como `balancer-web`.
        endereco: O IP.
        sub_rede: O nome da sub-rede onde esta.
        papel: `web`, `app`, `banco`, `bastion`, `gerencia` ou outro.
    """

    nome: str
    endereco: str
    sub_rede: str
    papel: str = ""

    def validar(self, problemas: list[str], sub_redes: dict[str, SubRede]) -> None:
        """Acumula os problemas deste no.

        Collect this node's problems.

        Args:
            problemas: Lista onde os problemas sao acumulados.
            sub_redes: As sub-redes por nome, para conferir a origem do IP.
        """
        if not self.nome.strip():
            problemas.append("no sem nome")
            return
        try:
            endereco = ipaddress.ip_address(self.endereco)
        except ValueError:
            problemas.append(f"no {self.nome!r}: endereco invalido {self.endereco!r}")
            return
        sub = sub_redes.get(self.sub_rede)
        if sub is None:
            problemas.append(
                f"no {self.nome!r}: sub-rede {self.sub_rede!r} nao declarada"
            )
        elif endereco not in sub.rede:
            problemas.append(
                f"no {self.nome!r}: endereco {self.endereco} esta fora da "
                f"sub-rede {self.sub_rede!r} ({sub.cidr})"
            )


@dataclass(frozen=True)
class Rota:
    """Uma rota da tabela de roteamento.

    A route of the routing table.

    Attributes:
        origem: A sub-rede de onde a rota parte.
        destino: A faixa de destino, ou `0.0.0.0/0` para a internet.
        proximo: O proximo salto, ou `None` para rota direta.
    """

    origem: str
    destino: str
    proximo: str | None = None

    @property
    def rede(self) -> ipaddress.IPv4Network:
        """A faixa de destino como objeto.

        The destination range as an object.
        """
        return ipaddress.ip_network(self.destino)

    @property
    def e_padrao(self) -> bool:
        """Se e a rota padrao.

        Whether it is the default route.
        """
        return self.rede.prefixlen == 0

    def alcanca(self, endereco: str) -> bool:
        """Se a rota alcanca um endereco.

        Whether the route reaches an address.

        Args:
            endereco: O endereco de destino.

        Returns:
            Verdadeiro se o endereco cai na faixa.
        """
        try:
            return ipaddress.ip_address(endereco) in self.rede
        except ValueError:
            return False

    def validar(self, problemas: list[str], sub_redes: dict[str, SubRede]) -> None:
        """Acumula os problemas desta rota.

        Collect this route's problems.

        Args:
            problemas: Lista onde os problemas sao acumulados.
            sub_redes: As sub-redes por nome.
        """
        if self.origem not in sub_redes:
            problemas.append(
                f"rota com origem {self.origem!r}: sub-rede nao declarada"
            )
        try:
            ipaddress.ip_network(self.destino, strict=False)
        except ValueError as erro:
            problemas.append(f"rota com destino {self.destino!r}: CIDR invalido ({erro})")


@dataclass(frozen=True)
class Arquitetura:
    """A VPC inteira, com sub-redes, nos e rotas.

    The whole VPC, with subnets, nodes and routes.

    Attributes:
        nome: O nome da VPC.
        sub_redes: As sub-redes, na ordem de declaracao.
        nos: Os nos, na ordem de declaracao.
        rotas: As rotas, na ordem de declaracao.
        origem: O arquivo de onde veio.
    """

    nome: str
    sub_redes: tuple[SubRede, ...] = ()
    nos: tuple[No, ...] = ()
    rotas: tuple[Rota, ...] = ()
    origem: str = ""

    def sub_rede(self, nome: str) -> SubRede | None:
        """Ache uma sub-rede pelo nome.

        Find a subnet by name.

        Args:
            nome: O nome da sub-rede.

        Returns:
            A sub-rede, ou `None`.
        """
        for sub in self.sub_redes:
            if sub.nome == nome:
                return sub
        return None

    def no(self, nome: str) -> No | None:
        """Ache um no pelo nome.

        Find a node by name.

        Args:
            nome: O nome do no.

        Returns:
            O no, ou `None`.
        """
        for item in self.nos:
            if item.nome == nome:
                return item
        return None

    def no_por_endereco(self, endereco: str) -> No | None:
        """Ache um no pelo endereco.

        Find a node by address.

        O pacote chega com endereco, nao com nome. Sem este metodo, quem
        rastreia um fluxo procura o no pelo nome e nao acha - porque o nome
        existe, mas a chave do mapa e o endereco.

        Args:
            endereco: O endereco do no.

        Returns:
            O no, ou `None` se o endereco nao for de um no declarado.
        """
        for item in self.nos:
            if item.endereco == endereco:
                return item
        return None

    def por_papel(self, papel: str) -> tuple[No, ...]:
        """Os nos de um papel.

        The nodes of a role.

        Args:
            papel: Como `banco` ou `bastion`.

        Returns:
            Os nos que tem o papel, na ordem de declaracao.
        """
        return tuple(n for n in self.nos if n.papel == papel)

    def sub_rede_de(self, endereco: str) -> SubRede | None:
        """A sub-rede a que um endereco pertence.

        The subnet an address belongs to.

        Args:
            endereco: O endereco.

        Returns:
            A sub-rede, ou `None` se o endereco nao pertence a VPC.
        """
        for sub in self.sub_redes:
            if sub.contem(endereco):
                return sub
        return None

    def rota_para(self, endereco: str, origem: str | None = None) -> Rota | None:
        """A rota que alcanca um endereco, a partir de uma origem.

        The route that reaches an address, from a source.

        Sem `origem`, devolve a primeira rota que alcanca o destino, independente
        de onde o pacote sai. Isso e util para perguntar "existe caminho?" e e
        **errado** para perguntar "por onde este pacote vai?".

        Com `origem`, filtra pelas rotas cujo lado de origem e a sub-rede do
        pacote. A diferenca importa: a rota padrao da DMZ alcanca qualquer
        endereco, e sem o filtro ela responderia "existe rota" mesmo para um
        pacote que nasce na camada de dados - e o motor mostraria um proximo
        salto que nunca seria usado.

        Args:
            endereco: O endereco de destino.
            origem: O endereco de origem, ou `None` para nao filtrar.

        Returns:
            A primeira rota que alcanca o destino a partir da origem, ou
            `None` se nenhuma alcancar.
        """
        sub_origem = self.sub_rede_de(origem) if origem else None
        candidatas = self.rotas
        if sub_origem is not None:
            candidatas = tuple(r for r in self.rotas if r.origem == sub_origem.nome)
        for rota in candidatas:
            if rota.alcanca(endereco):
                return rota
        return None

    def iter_camadas(self) -> Iterator[tuple[str, tuple[SubRede, ...]]]:
        """As camadas, da mais exposta para a mais interna.

        The layers, from most exposed to most internal.

        Yields:
            Par ``(camada, sub-redes)`` para cada camada declarada.
        """
        for camada in CAMPOS_DA_CAMADA:
            subs = tuple(s for s in self.sub_redes if s.camada == camada)
            if subs:
                yield camada, subs


def _converte_visao(bruta: object) -> str:
    """Converte o termo do YAML para a constante do modelo.

    Convert the YAML term to the model's constant.

    Args:
        bruta: O valor cru do YAML.

    Returns:
        A constante correspondente.

    Raises:
        ErroDeArquitetura: Se o termo nao for reconhecido.
    """
    termo = str(bruta or PRIVADA).strip().lower()
    mapa = {"publica": PUBLICA, "privada": PRIVADA, "private": PRIVADA, "public": PUBLICA}
    if termo not in mapa:
        raise ErroDeArquitetura(
            [f"visibilidade {bruta!r} desconhecida; use 'publica' ou 'privada'"]
        )
    return mapa[termo]


def de_documento(documento: dict[str, object], origem: str = "") -> Arquitetura:
    """Constroi a arquitetura a partir de um documento ja lido.

    Build the architecture from an already-read document.

    Args:
        documento: O mapa do YAML.
        origem: O caminho do arquivo, usado nos erros.

    Returns:
        A arquitetura validada.

    Raises:
        ErroDeArquitetura: Se o documento nao passar na validacao.
    """
    problemas: list[str] = []

    if not isinstance(documento, dict):
        raise ErroDeArquitetura(["o arquivo precisa ser um mapa no topo"], origem)

    sub_redes: list[SubRede] = []
    for item in documento.get("sub_redes") or []:
        if not isinstance(item, dict):
            problemas.append("sub_redes: entrada esperada como mapa")
            continue
        try:
            sub_redes.append(
                SubRede(
                    nome=str(item.get("nome", "")),
                    cidr=str(item.get("cidr", "")),
                    camada=str(item.get("camada", "")),
                    visibilidade=_converte_visao(item.get("visibilidade")),
                )
            )
        except ErroDeArquitetura as erro:
            problemas.extend(erro.problemas)

    por_nome = {s.nome: s for s in sub_redes}
    for sub in sub_redes:
        sub.validar(problemas)

    nos: list[No] = []
    vistos: set[str] = set()
    for item in documento.get("nos") or []:
        if not isinstance(item, dict):
            problemas.append("nos: entrada esperada como mapa")
            continue
        no = No(
            nome=str(item.get("nome", "")),
            endereco=str(item.get("endereco", "")),
            sub_rede=str(item.get("sub_rede", "")),
            papel=str(item.get("papel", "")),
        )
        no.validar(problemas, por_nome)
        if no.nome in vistos:
            problemas.append(f"no {no.nome!r} declarado duas vezes")
        vistos.add(no.nome)
        nos.append(no)

    rotas: list[Rota] = []
    for item in documento.get("rotas") or []:
        if not isinstance(item, dict):
            problemas.append("rotas: entrada esperada como mapa")
            continue
        rota = Rota(
            origem=str(item.get("origem", "")),
            destino=str(item.get("destino", "")),
            proximo=(str(item["proximo"]) if item.get("proximo") else None),
        )
        rota.validar(problemas, por_nome)
        rotas.append(rota)

    if problemas:
        raise ErroDeArquitetura(problemas, origem)

    return Arquitetura(
        nome=str(documento.get("vpc", "VPC-FICT")),
        sub_redes=tuple(sub_redes),
        nos=tuple(nos),
        rotas=tuple(rotas),
        origem=origem,
    )


def carregar(caminho: str | Path) -> Arquitetura:
    """Le a arquitetura de um YAML.

    Read the architecture from a YAML.

    Args:
        caminho: O arquivo.

    Returns:
        A arquitetura validada.

    Raises:
        ErroDeArquitetura: Se o arquivo nao existir ou nao passar na
            validacao.
    """
    import yaml

    caminho = Path(caminho)
    if not caminho.exists():
        raise ErroDeArquitetura([f"arquivo nao encontrado: {caminho}"], str(caminho))

    try:
        documento = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as erro:
        raise ErroDeArquitetura([f"YAML invalido: {erro}"], str(caminho)) from None

    return de_documento(documento, str(caminho))
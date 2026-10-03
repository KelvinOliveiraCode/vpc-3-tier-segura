"""O motor de decisao do firewall.

The firewall decision engine.

Este e o coracao do projeto. Uma regra de firewall se escreve em cinco minutos;
o que ensina e o motor - construir a avaliacao, rodar milhares de combinacoes
e ver o resultado virar quando uma regra se move de lugar.

## As quatro etapas de uma decisao

Cada avaliacao termina em exatamente uma etapa. A ordem e fixa:

1. **`relacionado`** - trafego de resposta de uma conexao ja permitida.
2. **`sem-rota`** - o pacote nao tem para onde ir.
3. **`permitido`** - uma regra permitiu.
4. **`bloqueado`** - uma regra negou.
5. **`sem-regra`** - nada disse nada.

A ordem importa. O trafego de resposta e verificado **antes** da rota porque
a resposta de uma conexao que aconteceu nao depende de a rota continuar de
pe: ela viaja pela propria conexao, que ja existe. Verificar a rota primeiro
transformaria toda resposta bem-sucedida em "sem-rota" num dia em que a tabela
muda, e o resultado seria um reporte falso.

## Rota e regra sao mecanismos diferentes

Uma regra diz o que e **permitido**. Uma rota diz o que e **possivel**. Um
pacote sem rota de retorno nao e "bloqueado por politica": ele simplesmente nao
chega, e nenhuma regra podia mudar isso.

E por isso que a verificacao de rota vem antes da tabela. A frase "o banco nao
aceita conexao da internet" e sustentada por **duas** coisas neste desenho: a
regra `internet-entra-no-banco` nega, e a camada de dados nao tem rota de
retorno. Qualquer uma das duas sozinha seria insuficiente - a regra sozinha
quebraria quando alguem acrescentasse uma rota, e a rota sozinha nao impediria
uma conexao de dentro da VPC.

## O padrao e negar

Quando nenhuma regra casa, o motor nega. Isso e o oposto de uma ACL implicita
que permite, e a escolha e o padrao de quem pensa em negacao explicita.

Um motor que permitsse por padrao transformaria **regra esquecida** em
**acesso concedido**, e o custo de um erro assim e silencioso e alto. Um motor
que nega por padrao transforma regra esquecida em acesso negado, que e
visivel, barulhento e corrigido em um minuto.

## Trafego de retorno

Uma conexao de ida tem uma resposta, e a resposta nao passa por regra nova.
Quando passa, produz duas consequencias ruins ao mesmo tempo: a resposta e
bloqueada, a conexao que a regra permitiu morre, e alguem acrescenta uma
regra de "resposta" que permite mais do que a intencao original.

Por isso o motor e **stateful**: um pacote marcado como relacionado ou
estabelecido, cujo par de enderecos esteja em `conexoes_estabelecidas`, passa
sem reabrir a tabela. A excecao para a resposta e o **estado da conexao**, nao
uma regra nova - e e por isso que ela nao cresce a cada problema novo.

O ponto delicate: o par e procurado **nas duas direcoes**. A resposta de uma
conexao e o mesmo par visto do outro lado, e procurar so na ordem original
faria toda resposta voltar para a avaliacao normal.
"""

from __future__ import annotations

from dataclasses import dataclass

from .rede import Arquitetura
from .regras import (
    ENTRADA,
    ESTABELECIDO,
    NEGAR,
    NOVO,
    PERMITIR,
    RELACIONADO,
    Regra,
    TabelaDeRegras,
)

# As etapas possiveis de uma decisao. Nomes estaveis porque o tracador e o
# relatorio comparam com eles.
ETAPA_RELACIONADO = "relacionado"
ETAPA_SEM_ROTA = "sem-rota"
ETAPA_PERMITIDO = "permitido"
ETAPA_BLOQUEADO = "bloqueado"
ETAPA_SEM_REGRA = "sem-regra"

ETAPAS = (
    ETAPA_RELACIONADO,
    ETAPA_SEM_ROTA,
    ETAPA_PERMITIDO,
    ETAPA_BLOQUEADO,
    ETAPA_SEM_REGRA,
)


@dataclass(frozen=True)
class Conexao:
    """Uma conexao a ser avaliada.

    A connection to be evaluated.

    Attributes:
        origem: Endereco de origem.
        destino: Endereco de destino.
        porta: Porta de destino.
        protocolo: `tcp` ou `udp`.
        sentido: `entrada` ou `saida`.
        id: Identificador do cenario, para o relatorio.
    """

    origem: str
    destino: str
    porta: int
    protocolo: str = "tcp"
    sentido: str = ENTRADA
    id: str = ""

    @property
    def par(self) -> tuple[str, str]:
        """O par de enderecos da conexao.

        The connection's address pair.
        """
        return (self.origem, self.destino)

    @property
    def e_resposta(self) -> bool:
        """Se o pacote e resposta de uma conexao existente.

        Whether the packet is a reply to an existing connection.
        """
        return self.campo in (RELACIONADO, ESTABELECIDO)

    @property
    def campo(self) -> str:
        """O campo de estado do pacote.

        The packet's state field.

        Vive aqui como propriedade, e nao como campo, porque e derivado do que
        o chamador **nao** preencheu. Um pacote sem campo e `novo` por padrao -
        e "novo" e o estado que exige mais prova para passar.
        """
        return getattr(self, "_campo", NOVO)

    @classmethod
    def com_campo(cls, campo: str, **campos: object) -> "Conexao":
        """Cria uma conexao ja com campo de estado.

        Create a connection already carrying a state field.

        O campo e keyword separado do resto porque nao faz parte da natureza
        de uma conexao: e do que se sabe **sobre** ela no momento da avaliacao.

        Args:
            campo: O campo de estado.
            **campos: Os campos normais de `Conexao`.

        Returns:
            A conexao com o campo definido.
        """
        conexao = cls(**campos)  # type: ignore[arg-type]
        object.__setattr__(conexao, "_campo", campo)
        return conexao


@dataclass(frozen=True)
class Decisao:
    """O resultado da avaliacao.

    The evaluation's result.

    Attributes:
        permitida: Se o trafego passa.
        regra: A regra que decidiu, ou `None` quando nenhuma decide.
        etapa: A etapa em que a decisao parou.
        motivo: Explicacao legivel, sempre preenchida.
    """

    permitida: bool
    regra: Regra | None
    etapa: str
    motivo: str

    @property
    def decideda_por_regra(self) -> bool:
        """Se a decisao veio de uma regra da tabela.

        Whether a table rule made the decision.
        """
        return self.regra is not None


def _tem_rota(arquitetura: Arquitetura, conexao: Conexao) -> tuple[bool, str]:
    """Se o pacote tem para onde ir.

    Whether the packet has anywhere to go.

    A verificacao so e feita quando a origem esta numa sub-rede **publica**. De
    uma sub-rede privada para outra, a conectividade e interna e a topologia do
    laboratorio nao modela roteamento interno; exigir rota para todo trafego
    interno faria o motor recusar comunicacao que a propria arquitetura
    declara existir.

    Args:
        arquitetura: A VPC.
        conexao: A conexao.

    Returns:
        O par ``(tem_rota, motivo)``.
    """
    origem = arquitetura.sub_rede_de(conexao.origem)
    if origem is None:
        return True, "origem fora da VPC; a topologia interna nao se aplica"

    if origem.visibilidade != "publica":
        return True, (
            f"trafego interno de {origem.nome} para "
            f"{arquitetura.sub_rede_de(conexao.destino)}: conectividade interna"
        )

    rota = arquitetura.rota_para(conexao.destino, origem=conexao.origem)
    if rota is None:
        return False, (
            f"sem rota de retorno de {conexao.origem} para {conexao.destino}: "
            f"a sub-rede {origem.nome} nao alcanca esse destino, e um pacote "
            "sem rota nao chega nem sendo permitido por regra"
        )
    return True, (
        f"rota de {rota.origem} para {rota.destino} via {rota.proximo or 'direto'}"
    )


def _parece_resposta(conexao: Conexao, estabelecidas: frozenset) -> bool:
    """Se o pacote e a resposta de uma conexao autorizada.

    Whether the packet replies to an authorized connection.

    O par e procurado **nas duas direcoes**, e a razao esta na natureza da
    resposta: ela e o mesmo par visto do outro lado. Se so a ordem original
    fosse procurada, toda resposta voltaria para a avaliacao normal e seria
    bloqueada por uma regra que existe para proteger a ida.

    Args:
        conexao: A conexao.
        estabelecidas: Os pares ja autorizados.

    Returns:
        Verdadeiro se o par estiver autorizado em qualquer sentido.
    """
    if not estabelecidas:
        return False
    par = conexao.par
    return par in estabelecidas or (par[1], par[0]) in estabelecidas


def avaliar(
    conexao: Conexao,
    tabela: TabelaDeRegras,
    arquitetura: Arquitetura,
    conexoes_estabelecidas: frozenset | None = None,
) -> Decisao:
    """Avalia uma conexao contra as regras e a topologia.

    Evaluate a connection against the rules and the topology.

    Args:
        conexao: A conexao a avaliar.
        tabela: A tabela de regras, na ordem de avaliacao.
        arquitetura: A VPC.
        conexoes_estabelecidas: Pares de enderecos ja autorizados, para o
            trafego de resposta. `None` equivale a nenhum.

    Returns:
        A decisao, com a etapa em que parou.
    """
    estabelecidas = conexoes_estabelecidas or frozenset()

    # --- 1. trafego de resposta -------------------------------------------
    # Antes da rota, e antes da tabela: a resposta viaja pela conexao que ja
    # existe, e nao depende de a tabela de rotas continuar igual.
    if conexao.e_resposta:
        if _parece_resposta(conexao, estabelecidas):
            return Decisao(
                permitida=True,
                regra=None,
                etapa=ETAPA_RELACIONADO,
                motivo=(
                    f"trafego {conexao.campo} de {conexao.par[0]} para "
                    f"{conexao.par[1]}: resposta de conexao ja autorizada, e "
                    "por isso nao reabre a tabela"
                ),
            )
        # Um pacote marcado como resposta cujo par nao esta autorizado nao e
        # resposta de nada. Cai para a avaliacao normal, como se fosse novo -
        # senao bastaria marcar qualquer pacote como 'relacionado' para
        # passar por cima de todas as regras.
        return _avalia_pela_tabela(conexao, tabela, arquitetura)

    # --- 2. rota ----------------------------------------------------------
    tem_rota, motivo_rota = _tem_rota(arquitetura, conexao)
    if not tem_rota:
        return Decisao(
            permitida=False,
            regra=None,
            etapa=ETAPA_SEM_ROTA,
            motivo=motivo_rota,
        )

    # --- 3. tabela --------------------------------------------------------
    return _avalia_pela_tabela(conexao, tabela, arquitetura, motivo_rota)


def _avalia_pela_tabela(
    conexao: Conexao,
    tabela: TabelaDeRegras,
    arquitetura: Arquitetura,
    motivo_rota: str = "",
) -> Decisao:
    """Percorre a tabela na ordem e devolve a decisao da primeira regra que casa.

    Walk the table in order and return the first matching rule's decision.

    Args:
        conexao: A conexao.
        tabela: A tabela de regras.
        arquitetura: A VPC.
        motivo_rota: O motivo da verificacao de rota, para o caso de cair na
            etapa `sem-regra`.

    Returns:
        A decisao.
    """
    for regra in tabela.por_sentido(conexao.sentido):
        if not regra.casa(
            conexao.sentido,
            conexao.origem,
            conexao.destino,
            conexao.porta,
            conexao.protocolo,
            conexao.campo,
        ):
            continue
        permitida = regra.acao == PERMITIR
        return Decisao(
            permitida=permitida,
            regra=regra,
            etapa=ETAPA_PERMITIDO if permitida else ETAPA_BLOQUEADO,
            motivo=regra.motivo or f"decidido pela regra {regra.identificador}",
        )

    # Nenhuma regra casou. O motor nega: regra esquecida vira acesso negado,
    # que e visivel, e nao acesso concedido, que e silencioso.
    destino = arquitetura.sub_rede_de(conexao.destino)
    onde = destino.nome if destino is not None else conexao.destino
    extra = f" {motivo_rota};" if motivo_rota else ""
    return Decisao(
        permitida=False,
        regra=None,
        etapa=ETAPA_SEM_REGRA,
        motivo=(
            f"nenhuma regra de {conexao.sentido} casa com "
            f"{conexao.origem} para {conexao.destino}:{conexao.porta} "
            f"em {onde}.{extra} O motor nega por padrao: regra esquecida "
            "vira acesso negado, que aparece, e nao acesso concedido"
        ),
    )
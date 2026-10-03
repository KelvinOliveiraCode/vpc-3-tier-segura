"""Prova de aceite do vpcsim.

vpcsim acceptance proof.

O criterio de aceite do projeto tem duas metades:

1. **Os vinte cenarios tem resultado esperado e o motor concorda com todos.**
   Nao e "os que passam": todos. Um motor que concorda com dezenove e um motor
   com um caso errado, e o caso errado e o que interessa.
2. **O tracador mostra o ponto exato do bloqueio.** Nao basta o resultado: um
   "bloqueado" sem dizer qual regra decidiu e um resultado que ninguem pode
   corrigir.

O script verifica ainda as tres etapas que so aparecem com estado montado antes
- resposta permitida pelo estado da conexao, pacote sem rota e pacote sem
regra - porque sao as que a suite nao cobre sozinha.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from vpcsim import cenarios as modulo_cenarios  # noqa: E402
from vpcsim import firewall as modulo_firewall  # noqa: E402
from vpcsim import rede as modulo_rede  # noqa: E402
from vpcsim import regras as modulo_regras  # noqa: E402
from vpcsim.cenarios import BLOQUEADO, PERMITIDO  # noqa: E402
from vpcsim.firewall import Conexao, avaliar  # noqa: E402
from vpcsim.tracador import formatar, tracar  # noqa: E402

ARQUITETURA = RAIZ / "dados" / "arquitetura.yaml"
REGRAS = RAIZ / "dados" / "regras.yaml"
CENARIOS = RAIZ / "dados" / "cenarios-teste.yaml"

TOTAL_ESPERADO = 20


class Falha(Exception):
    """Uma condicao de aceite nao foi satisfeita."""


def checar(condicao: bool, mensagem: str) -> None:
    """Falha se a condicao e falsa.

    Fail if the condition is false.

    Args:
        condicao: A condicao.
        mensagem: O que deu errado, se ela for falsa.

    Raises:
        Falha: Se a condicao for falsa.
    """
    if not condicao:
        raise Falha(mensagem)


def estado_de(cenario) -> frozenset:
    """Os pares autorizados de um cenario, nos dois sentidos.

    Args:
        cenario: O cenario.

    Returns:
        O conjunto de pares.
    """
    pares: set[tuple[str, str]] = set()
    for origem, destino in cenario.estabelecidas:
        pares.add((origem, destino))
        pares.add((destino, origem))
    return frozenset(pares)


def conexao_de(cenario) -> Conexao:
    """A conexao do motor para um cenario.

    Args:
        cenario: O cenario.

    Returns:
        A conexao, com o campo de estado.
    """
    return Conexao.com_campo(
        cenario.campo,
        origem=cenario.origem,
        destino=cenario.destino,
        porta=cenario.porta,
        protocolo=cenario.protocolo,
        sentido=cenario.sentido,
        id=cenario.id,
    )


def test_contagem() -> tuple:
    """O arquivo tem os vinte cenarios que a especificacao pede.

    Returns:
        O par ``(cenarios, numero_de_cenarios)``.
    """
    print("1) o arquivo tem os cenarios que a especificacao pede")
    casos = modulo_cenarios.carregar(CENARIOS)
    checar(
        len(casos) == TOTAL_ESPERADO,
        f"esperava {TOTAL_ESPERADO} cenarios, vieram {len(casos)}",
    )
    print(f"   {len(casos)} cenarios, todos com resultado esperado")
    return casos, len(casos)


def test_concordancia(casos, arquitetura, tabela) -> None:
    """O motor concorda com o esperado de todos os cenarios.

    Args:
        casos: Os cenarios.
        arquitetura: A VPC.
        tabela: A tabela de regras.

    Raises:
        Falha: Se algum cenario divergir.
    """
    print("\n2) o motor concorda com os vinte cenarios")
    divergentes: list[str] = []
    for caso in casos:
        decisao = avaliar(
            conexao_de(caso), tabela, arquitetura,
            conexoes_estabelecidas=estado_de(caso),
        )
        obtido = PERMITIDO if decisao.permitida else BLOQUEADO
        if obtido != caso.esperado:
            divergentes.append(f"{caso.id} (esperado {caso.esperado}, veio {obtido})")

    checar(not divergentes, "cenarios divergentes: " + "; ".join(divergentes))
    print(f"   {len(casos)} de {len(casos)} concordam com o motor")


def test_tracador_mostra_a_regra(casos, arquitetura, tabela) -> None:
    """O tracador diz qual regra decidiu, e mostra o caminho.

    Args:
        casos: Os cenarios.
        arquitetura: A VPC.
        tabela: A tabela de regras.

    Raises:
        Falha: Se algum tracado nao mostrar a regra que decidiu.
    """
    print("\n3) o tracador mostra o ponto exato do bloqueio")
    sem_regra: list[str] = []
    etapas: dict[str, int] = {}

    for caso in casos:
        traco = tracar(
            conexao_de(caso), tabela, arquitetura,
            conexoes_estabelecidas=estado_de(caso),
        )
        etapas[traco.decisao.etapa] = etapas.get(traco.decisao.etapa, 0) + 1
        texto = formatar(traco)

        # Todo tracado tem de dizer o veredito e a etapa.
        if "VEREDITO" not in texto:
            sem_regra.append(f"{caso.id}: sem VEREDITO")

        # Quando a decisao veio de uma regra, o tracado tem de citar a regra.
        if traco.decisao.decideda_por_regra:
            if traco.decisao.regra.identificador not in texto:
                sem_regra.append(f"{caso.id}: regra nao citada")

    checar(not sem_regra, "tracos incompletos: " + "; ".join(sem_regra))
    print(f"   20 de 20 tracados com veredito e regra citada")
    print(f"   etapas cobertas: {etapas}")


def test_as_tres_etapas(arquitetura, tabela) -> None:
    """As etapas de estado, rota e sem-regra aparecem quando devem.

    Args:
        arquitetura: A VPC.
        tabela: A tabela de regras.

    Raises:
        Falha: Se alguma etapa nao aparecer.
    """
    print("\n4) as etapas de estado, rota e sem-regra aparecem")
    visto: set[str] = set()

    # resposta permitida pelo estado, sem regra que a autorize sozinha
    resposta = Conexao.com_campo(
        "relacionado",
        origem="10.30.0.11", destino="10.20.0.11",
        porta=5432, protocolo="tcp", sentido="saida", id="prova-relacionado",
    )
    d = avaliar(
        resposta, tabela, arquitetura,
        conexoes_estabelecidas=frozenset({("10.20.0.11", "10.30.0.11")}),
    )
    checar(
        d.etapa == modulo_firewall.ETAPA_RELACIONADO,
        f"resposta autorizada caiu em {d.etapa}, esperado relacionado",
    )
    visto.add(d.etapa)

    # o MESMO pacote, sem o estado: tem de cair na tabela e ser negado
    sem_estado = Conexao(
        origem="10.30.0.11", destino="10.20.0.11",
        porta=5432, protocolo="tcp", sentido="saida", id="prova-sem-estado",
    )
    d2 = avaliar(sem_estado, tabela, arquitetura)
    checar(
        d2.permitida is False,
        "resposta sem estado autorizado foi permitida; marcar qualquer pacote "
        "como relacionado contornaria todas as regras",
    )
    visto.add(d2.etapa)

    # pacote que morre por topologia: saida da faixa do parceiro, que tem rota
# apenas para si e nenhuma para a camada de dados
    sem_rota = Conexao(
        origem="198.51.100.10", destino="10.30.0.11",
        porta=5432, protocolo="tcp", sentido="entrada", id="prova-sem-rota",
    )
    d3 = avaliar(sem_rota, tabela, arquitetura)
    checar(
        d3.etapa == modulo_firewall.ETAPA_SEM_ROTA,
        f"pacote sem rota caiu em {d3.etapa}, esperado sem-rota",
    )
    visto.add(d3.etapa)

    # pacote que nenhuma regra menciona
    nao_maps = Conexao(
        origem="10.10.0.5", destino="10.99.99.99",
        porta=9999, protocolo="tcp", sentido="saida", id="prova-sem-regra",
    )
    d4 = avaliar(nao_maps, tabela, arquitetura)
    checar(
        d4.etapa == modulo_firewall.ETAPA_SEM_REGRA,
        f"pacote sem regra caiu em {d4.etapa}, esperado sem-regra",
    )
    visto.add(d4.etapa)

    print(f"   etapas verificadas: {sorted(visto)}")


def principal() -> int:
    """Roda a prova de aceite.

    Run the acceptance proof.

    Returns:
        0 se tudo passar, 1 se alguma condicao falhar.
    """
    arquitetura = modulo_rede.carregar(ARQUITETURA)
    tabela = modulo_regras.carregar(REGRAS)

    try:
        casos, _ = test_contagem()
        test_concordancia(casos, arquitetura, tabela)
        test_tracador_mostra_a_regra(casos, arquitetura, tabela)
        test_as_tres_etapas(arquitetura, tabela)
    except Falha as erro:
        print("\nACEITE FALHOU:")
        print(f"  - {erro}")
        return 1

    print(
        "\nok: os 20 cenarios concordam com o motor, e o tracador mostra o "
        "ponto exato de cada decisao"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
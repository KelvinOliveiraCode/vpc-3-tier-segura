"""Testes do motor de decisao do firewall.

Firewall decision engine tests.

O motor tem cinco etapas possiveis, e as cinco precisam aparecer nos testes:
um motor testado em menos etapas e um motor cuja etapa nao testada decide
contra o que ninguem verificou.

A ordem das etapas tambem e testada, e e ela que importa mais. Rota antes da
tabela, resposta antes da rota: trocar duas etapas e trocar o resultado de
milhares de pacotes ao mesmo tempo, e nenhum teste de unidade pegaria isso
exceto um que verifica a prioridade na ordem certa.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vpcsim import firewall as modulo_firewall
from vpcsim import rede as modulo_rede
from vpcsim import regras as modulo_regras
from vpcsim.firewall import Conexao, Decisao, avaliar
from vpcsim.regras import NOVO, PERMITIR

RAIZ = Path(__file__).resolve().parent.parent
ARQUITETURA = RAIZ / "dados" / "arquitetura.yaml"
REGRAS = RAIZ / "dados" / "regras.yaml"


@pytest.fixture(scope="module")
def arquitetura():
    return modulo_rede.carregar(ARQUITETURA)


@pytest.fixture(scope="module")
def tabela():
    return modulo_regras.carregar(REGRAS)


def permite(conexao, tabela, arquitetura, estabelecidas=None):
    """Avalia e devolve so o veredito.

    Evaluate and return only the verdict.

    Args:
        conexao: A conexao.
        tabela: A tabela de regras.
        arquitetura: A VPC.
        estabelecidas: Pares autorizados.

    Returns:
        Verdadeiro se o trafego passa.
    """
    return avaliar(
        conexao, tabela, arquitetura,
        conexoes_estabelecidas=estabelecidas,
    ).permitida


class TestOsQuatroObrigatorios:
    """Os quatro casos que a especificacao exige."""

    def test_internet_nao_entra_no_banco(self, tabela, arquitetura) -> None:
        conexao = Conexao(
            origem="203.0.113.50", destino="10.30.0.11", porta=5432,
            protocolo="tcp", sentido="entrada", id="spec-1",
        )
        decisao = avaliar(conexao, tabela, arquitetura)
        assert decisao.permitida is False
        assert decisao.etapa == modulo_firewall.ETAPA_BLOQUEADO

    def test_bastion_entra_no_banco(self, tabela, arquitetura) -> None:
        conexao = Conexao(
            origem="10.10.0.5", destino="10.30.0.11", porta=5432,
            protocolo="tcp", sentido="entrada", id="spec-2",
        )
        assert permite(conexao, tabela, arquitetura) is True

    def test_aplicacao_fala_com_banco(self, tabela, arquitetura) -> None:
        conexao = Conexao(
            origem="10.20.0.11", destino="10.30.0.11", porta=5432,
            protocolo="tcp", sentido="entrada", id="spec-3",
        )
        assert permite(conexao, tabela, arquitetura) is True

    def test_internet_fala_com_aplicacao_via_web(self, tabela, arquitetura) -> None:
        conexao = Conexao(
            origem="203.0.113.50", destino="203.0.113.11", porta=443,
            protocolo="tcp", sentido="entrada", id="spec-4",
        )
        assert permite(conexao, tabela, arquitetura) is True


class TestRotasProprias:
    """A condicao de rota independe da regra que a invoca."""

    def test_sem_rota_publica_nao_chega(self, tabela, arquitetura) -> None:
        conexao = Conexao(
            origem="198.51.100.10", destino="10.30.0.11", porta=5432,
            protocolo="tcp", sentido="entrada", id="sem-rota",
        )
        decisao = avaliar(conexao, tabela, arquitetura)
        assert decisao.permitida is False
        assert decisao.etapa == modulo_firewall.ETAPA_SEM_ROTA

    def test_rota_citada_no_motivo(self, tabela, arquitetura) -> None:
        conexao = Conexao(
            origem="198.51.100.10", destino="10.30.0.11", porta=5432,
            protocolo="tcp", sentido="entrada", id="motivo-rota",
        )
        decisao = avaliar(conexao, tabela, arquitetura)
        assert "rota" in decisao.motivo


class TestTrafegoDeRetorno:
    """O estado da conexao substitui a tabela para a resposta."""

    def _estabelecidas(self):
        return frozenset({("10.20.0.11", "10.30.0.11")})

    def test_resposta_pass_por_estado(self, tabela, arquitetura) -> None:
        conexao = Conexao.com_campo(
            "relacionado",
            origem="10.30.0.11", destino="10.20.0.11", porta=5432,
            protocolo="tcp", sentido="saida", id="resposta",
        )
        decisao = avaliar(
            conexao, tabela, arquitetura,
            conexoes_estabelecidas=self._estabelecidas(),
        )
        assert decisao.permitida is True
        assert decisao.etapa == modulo_firewall.ETAPA_RELACIONADO
        assert decisao.regra is None, "resposta passa por estado, nao por regra"

    def test_resposta_sem_estado_cai_na_tabela(self, tabela, arquitetura) -> None:
        # Marcar qualquer pacote como 'relacionado' nao pode contornar as
        # regras. Sem o par autorizado, o pacote segue a avaliacao normal -
        # e neste caso a tabela nega.
        conexao = Conexao.com_campo(
            "relacionado",
            origem="10.30.0.11", destino="10.20.0.11", porta=5432,
            protocolo="tcp", sentido="saida", id="falsa-resposta",
        )
        decisao = avaliar(conexao, tabela, arquitetura)
        assert decisao.permitida is False

    def test_par_vale_nas_duas_direcoes(self, tabela, arquitetura) -> None:
        # A resposta e o mesmo par visto do outro lado. Se so a ordem
        # original fosse procurada, a resposta cairia na tabela.
        conexao = Conexao.com_campo(
            "relacionado",
            origem="10.20.0.11", destino="10.30.0.11", porta=5432,
            protocolo="tcp", sentido="entrada", id="inverso",
        )
        decisao = avaliar(
            conexao, tabela, arquitetura,
            conexoes_estabelecidas=self._estabelecidas(),
        )
        assert decisao.permitida is True

    def test_estabelecido_tambem_passa_por_estado(self, tabela, arquitetura) -> None:
        conexao = Conexao.com_campo(
            "estabelecido",
            origem="10.30.0.11", destino="10.20.0.11", porta=5432,
            protocolo="tcp", sentido="saida", id="estab",
        )
        decisao = avaliar(
            conexao, tabela, arquitetura,
            conexoes_estabelecidas=self._estabelecidas(),
        )
        assert decisao.permitida is True

    def test_campo_de_estado_mostra_qual_eh(self, tabela, arquitetura) -> None:
        conexao = Conexao.com_campo(
            "relacionado",
            origem="10.30.0.11", destino="10.20.0.11", porta=5432,
            protocolo="tcp", sentido="saida", id="qual",
        )
        decisao = avaliar(
            conexao, tabela, arquitetura,
            conexoes_estabelecidas=self._estabelecidas(),
        )
        assert "relacionado" in decisao.motivo


class TestOrdemDasRegras:
    """A primeira que casa decide."""

    def test_duas_regras_que_casam(self, tabela, arquitetura) -> None:
        # Ha uma negar para internet->banco e uma permitir generica nao ha:
        # o que interessa e que a negar vem antes da linha final.
        conexao = Conexao(
            origem="203.0.113.50", destino="10.30.0.11", porta=22,
            protocolo="tcp", sentido="entrada", id="ordem",
        )
        decisao = avaliar(conexao, tabela, arquitetura)
        assert decisao.permitida is False
        assert decisao.regra is not None
        assert decisao.regra.identificador == "internet-entra-no-banco-por-outra-porta"

    def test_porta_errada_nao_casa(self, tabela, arquitetura) -> None:
        conexao = Conexao(
            origem="203.0.113.50", destino="203.0.113.11", porta=22,
            protocolo="tcp", sentido="entrada", id="porta-errada",
        )
        assert permite(conexao, tabela, arquitetura) is False


class TestSemRegra:
    """Quando nada diz nada, o motor nega."""

    def test_porta_fora_da_tabela_cai_no_limite_final(self, tabela, arquitetura) -> None:
        # A tabela tem uma regra final que nega tudo. Um pacote que nenhuma
        # regra menciona nao chega na etapa `sem-regra`: ele e bloqueado pela
        # regra final, e e isso que aparece no tracador. A etapa `sem-regra`
        # existe para tabelas sem regra final, e o proximo teste prova.
        conexao = Conexao(
            origem="10.10.0.5", destino="10.30.0.11", porta=9999,
            protocolo="tcp", sentido="entrada", id="fantasma",
        )
        decisao = avaliar(conexao, tabela, arquitetura)
        assert decisao.permitida is False
        assert decisao.etapa == modulo_firewall.ETAPA_BLOQUEADO
        assert decisao.regra is not None
        assert decisao.regra.identificador == "nega-o-que-nada-permite"

    def test_sem_regra_quando_a_tabela_nao_tem_limite_final(
        self, tabela, arquitetura
    ) -> None:
        # Uma tabela sem a regra final deixa o pacote cair na etapa
        # `sem-regra`, com o mesmo veredito mas origem diferente. A diferenca
        # importa para quem opera: `bloqueado` diz qual regra decidiu, e
        # `sem-regra` diz que nenhuma regra soube decidir.
        from vpcsim.regras import TabelaDeRegras

        sem_final = TabelaDeRegras(
            regras=tuple(
                r for r in tabela.regras
                if r.identificador != "nega-o-que-nada-permite"
            )
        )
        conexao = Conexao(
            origem="10.10.0.5", destino="10.30.0.11", porta=9999,
            protocolo="tcp", sentido="entrada", id="sem-final",
        )
        decisao = avaliar(conexao, sem_final, arquitetura)
        assert decisao.permitida is False
        assert decisao.etapa == modulo_firewall.ETAPA_SEM_REGRA
        assert decisao.regra is None, "sem-regra nao vem de regra nenhuma"

    def test_o_motivo_diz_porque_negou(self, tabela, arquitetura) -> None:
        conexao = Conexao(
            origem="10.10.0.5", destino="10.30.0.11", porta=9999,
            protocolo="tcp", sentido="entrada", id="motivo-negou",
        )
        decisao = avaliar(conexao, tabela, arquitetura)
        assert "nega" in decisao.motivo

    def test_negacao_e_oposto_de_acl_implicita(self, tabela, arquitetura) -> None:
        # Uma ACL que nao lista deixa passar; um motor que nao lista bloqueia.
        # A diferenca tem de estar documentada na decisao, e nao so no
        # codigo: quem opera precisa saber qual dos dois padroes esta valendo.
        conexao = Conexao(
            origem="10.10.0.5", destino="10.30.0.11", porta=1,
            protocolo="udp", sentido="entrada", id="udp-1",
        )
        decisao = avaliar(conexao, tabela, arquitetura)
        assert decisao.permitida is False


class TestConexao:
    """O tipo de entrada do motor."""

    def test_par(self) -> None:
        conexao = Conexao(
            origem="a", destino="b", porta=80, protocolo="tcp",
            sentido="entrada", id="x",
        )
        assert conexao.par == ("a", "b")

    def test_novo_e_o_campo_padrao(self) -> None:
        conexao = Conexao(
            origem="a", destino="b", porta=80, protocolo="tcp",
            sentido="entrada", id="x",
        )
        assert conexao.campo == NOVO
        assert conexao.e_resposta is False

    def test_com_campo_relacionado(self) -> None:
        conexao = Conexao.com_campo(
            "relacionado",
            origem="a", destino="b", porta=80, protocolo="tcp",
            sentido="saida", id="x",
        )
        assert conexao.campo == "relacionado"
        assert conexao.e_resposta is True


class TestDecisao:
    """O tipo de saida do motor."""

    def test_decideda_por_regra(self, tabela) -> None:
        regra = tabela.por_identificador("internet-entra-no-banco")
        from vpcsim.firewall import Decisao

        decisao = Decisao(
            permitida=False, regra=regra,
            etapa=modulo_firewall.ETAPA_BLOQUEADO, motivo="x",
        )
        assert decisao.decideda_por_regra is True

    def test_sem_regra(self) -> None:
        from vpcsim.firewall import Decisao

        decisao = Decisao(
            permitida=False, regra=None,
            etapa=modulo_firewall.ETAPA_SEM_REGRA, motivo="x",
        )
        assert decisao.decideda_por_regra is False

    def test_etapas_sao_conhecidas(self, tabela, arquitetura) -> None:
        from vpcsim.cenarios import carregar

        casos = carregar(RAIZ / "dados" / "cenarios-teste.yaml")
        etapas = set()
        for caso in casos:
            decisao = avaliar(
                Conexao.com_campo(
                    caso.campo, origem=caso.origem, destino=caso.destino,
                    porta=caso.porta, protocolo=caso.protocolo,
                    sentido=caso.sentido, id=caso.id,
                ),
                tabela, arquitetura,
                conexoes_estabelecidas=frozenset(
                    {p for par in caso.estabelecidas for p in (par, par[::-1])}
                ),
            )
            etapas.add(decisao.etapa)
        assert etapas <= set(modulo_firewall.ETAPAS), etapas - set(modulo_firewall.ETAPAS)
        assert modulo_firewall.ETAPA_BLOQUEADO in etapas
        assert modulo_firewall.ETAPA_PERMITIDO in etapas
        assert modulo_firewall.ETAPA_RELACIONADO in etapas
        assert modulo_firewall.ETAPA_SEM_ROTA in etapas
        assert modulo_firewall.ETAPA_SEM_REGRA in etapas
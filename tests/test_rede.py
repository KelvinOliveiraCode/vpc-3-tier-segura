"""Testes do modelo de rede.

Network model tests.

O modelo descreve a VPC: sub-redes, nos, rotas. Um erro aqui nao aparece como
"teste vermelho" em producao - aparece como o firewall decidindo sobre uma
topologia que nao existe. Por isso estes testes verificam a estrutura antes de
qualquer avaliacao.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vpcsim import rede
from vpcsim.rede import (
    Arquitetura,
    ErroDeArquitetura,
    No,
    Rota,
    SubRede,
    carregar,
    de_documento,
)

RAIZ = Path(__file__).resolve().parent.parent
ARQUITETURA = RAIZ / "dados" / "arquitetura.yaml"


@pytest.fixture(scope="module")
def arquitetura() -> Arquitetura:
    return carregar(ARQUITETURA)


class TestSubRede:
    """O tipo de sub-rede."""

    def test_gateway_e_o_primeiro(self) -> None:
        sub = SubRede(nome="x", cidr="10.0.0.0/24", camada="dmz", visibilidade="publica")
        assert sub.gateway == "10.0.0.1"

    def test_contem(self) -> None:
        sub = SubRede(nome="x", cidr="10.0.0.0/24", camada="dmz")
        assert sub.contem("10.0.0.99") is True
        assert sub.contem("10.0.1.1") is False
        assert sub.contem("nao-e-ip") is False

    def test_cidr_invalido(self) -> None:
        with pytest.raises(ErroDeArquitetura):
            SubRede(nome="x", cidr="nao-e-cidr", camada="dmz")

    def test_camada_desconhecida(self) -> None:
        with pytest.raises(ErroDeArquitetura):
            SubRede(nome="x", cidr="10.0.0.0/24", camada="espaco")

    def test_visibilidade_desconhecida(self) -> None:
        with pytest.raises(ErroDeArquitetura):
            SubRede(nome="x", cidr="10.0.0.0/24", camada="dmz", visibilidade="vidro")

    def test_nome_vazio(self) -> None:
        sub = SubRede(nome="  ", cidr="10.0.0.0/24", camada="dmz")
        problemas: list[str] = []
        sub.validar(problemas)
        assert problemas


class TestRota:
    """O tipo de rota."""

    def test_rota_padrao(self) -> None:
        assert Rota(origem="a", destino="0.0.0.0/0").e_padrao is True
        assert Rota(origem="a", destino="10.0.0.0/24").e_padrao is False

    def test_alcanca(self) -> None:
        rota = Rota(origem="a", destino="10.30.0.0/24")
        assert rota.alcanca("10.30.0.99") is True
        assert rota.alcanca("10.20.0.1") is False
        assert rota.alcanca("nao-e-ip") is False

    def test_origem_nao_declarada(self) -> None:
        rota = Rota(origem="fantasma", destino="10.0.0.0/24")
        problemas: list[str] = []
        rota.validar(problemas, {})
        assert any("fantasma" in p for p in problemas)

    def test_destino_invalido(self) -> None:
        rota = Rota(origem="a", destino="nao-e-cidr")
        problemas: list[str] = []
        rota.validar(problemas, {"a": object()})
        assert any("CIDR invalido" in p for p in problemas)


class TestNo:
    """O tipo de no."""

    def test_no_fora_da_sub_rede(self) -> None:
        sub = SubRede(nome="s", cidr="10.0.0.0/24", camada="dmz")
        no = No(nome="n", endereco="10.9.9.9", sub_rede="s")
        problemas: list[str] = []
        no.validar(problemas, {"s": sub})
        assert any("fora da" in p for p in problemas)

    def test_no_em_sub_rede_inexistente(self) -> None:
        no = No(nome="n", endereco="10.0.0.1", sub_rede="fantasma")
        problemas: list[str] = []
        no.validar(problemas, {})
        assert any("nao declarada" in p for p in problemas)

    def test_endereco_invalido(self) -> None:
        no = No(nome="n", endereco="nao-e-ip", sub_rede="s")
        problemas: list[str] = []
        no.validar(problemas, {})
        assert problemas


class TestArquitetura:
    """As consultas sobre a VPC."""

    def test_no_por_nome(self, arquitetura: Arquitetura) -> None:
        assert arquitetura.no("bastion") is not None
        assert arquitetura.no("nao-existe") is None

    def test_no_por_endereco(self, arquitetura: Arquitetura) -> None:
        assert arquitetura.no_por_endereco("10.30.0.11").nome == "banco-01"
        assert arquitetura.no_por_endereco("8.8.8.8") is None

    def test_por_papel(self, arquitetura: Arquitetura) -> None:
        assert len(arquitetura.por_papel("banco")) == 1
        assert arquitetura.por_papel("nao-existe") == ()

    def test_sub_rede_de(self, arquitetura: Arquitetura) -> None:
        assert arquitetura.sub_rede_de("10.30.0.99").nome == "dados-privada"
        assert arquitetura.sub_rede_de("1.1.1.1") is None

    def test_rota_para_sem_origem(self, arquitetura: Arquitetura) -> None:
        # Sem filtro, a primeira que alcanca e a resposta. Util para perguntar
        # "existe caminho?", errado para "por onde este pacote vai?".
        assert arquitetura.rota_para("10.30.0.11") is not None

    def test_rota_para_com_origem(self, arquitetura: Arquitetura) -> None:
        # A rota padrao da DMZ nao pode responder por um pacote que nasce na
        # camada de dados: o proximo salto exibido nunca seria usado.
        rota = arquitetura.rota_para("10.30.0.11", origem="10.30.0.11")
        assert rota is None or rota.origem != "dmz-publica"

    def test_rota_inexistente(self, arquitetura: Arquitetura) -> None:
        assert arquitetura.rota_para("10.99.99.99", origem="198.51.100.10") is None

    def test_iter_camadas_na_ordem(self, arquitetura: Arquitetura) -> None:
        camadas = [c for c, _ in arquitetura.iter_camadas()]
        assert camadas.index("dmz") < camadas.index("aplicacao")
        assert camadas.index("aplicacao") < camadas.index("dados")

    def test_a_vpn_tem_oito_nos(self, arquitetura: Arquitetura) -> None:
        # Sete originais mais o web-parceiro. Se o numero mudar sem que o
        # teste seja atualizado, significa que a arquitetura mudou - e e
        # exatamente isso que o teste quer pegar.
        assert len(arquitetura.nos) == 8, [n.nome for n in arquitetura.nos]


class TestCarga:
    """A leitura do YAML."""

    def test_arquivo_inexistente(self) -> None:
        with pytest.raises(ErroDeArquitetura):
            carregar(RAIZ / "dados" / "nao-existe.yaml")

    def test_yaml_invalido(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "ruim.yaml"
        arquivo.write_text("a: [1, 2\n", encoding="utf-8")
        with pytest.raises(ErroDeArquitetura):
            carregar(arquivo)

    def test_topo_nao_e_mapa(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "lista.yaml"
        arquivo.write_text("- a\n", encoding="utf-8")
        with pytest.raises(ErroDeArquitetura):
            carregar(arquivo)

    def test_no_duplicado(self) -> None:
        with pytest.raises(ErroDeArquitetura):
            de_documento({
                "nos": [
                    {"nome": "x", "endereco": "10.0.0.1", "sub_rede": "s"},
                    {"nome": "x", "endereco": "10.0.0.2", "sub_rede": "s"},
                ],
                "sub_redes": [
                    {"nome": "s", "cidr": "10.0.0.0/24", "camada": "dmz"}
                ],
            })

    def test_visibilidade_abreviada(self) -> None:
        arquitetura = de_documento({
            "sub_redes": [
                {"nome": "s", "cidr": "10.0.0.0/24", "camada": "dmz",
                 "visibilidade": "public"}
            ]
        })
        assert arquitetura.sub_redes[0].visibilidade == "publica"
"""Testes das regras e do tracador.

Rule and tracer tests.

As regras sao o que o subagent K1 nao chegou a escrever sozinho - o motor e
meu - e o tracador veio do K3 com ressalva. Estes testes fixam o contrato de
ambos: o que `Regra.casa` aceita, o que `TabelaDeRegras` garante, e o que um
tracado precisa mostrar para ser util.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vpcsim import rede as modulo_rede
from vpcsim import regras as modulo_regras
from vpcsim.firewall import Conexao
from vpcsim.regras import ENTRADA, NOVO, PERMITIR, Regra, TabelaDeRegras, carregar
from vpcsim.tracador import Passo, Traco, formatar, tracar

RAIZ = Path(__file__).resolve().parent.parent
ARQUITETURA = RAIZ / "dados" / "arquitetura.yaml"
REGRAS = RAIZ / "dados" / "regras.yaml"


@pytest.fixture(scope="module")
def arquitetura():
    return modulo_rede.carregar(ARQUITETURA)


@pytest.fixture(scope="module")
def tabela():
    return carregar(REGRAS)


def regra_base(**campos) -> Regra:
    """Uma regra de teste valida.

    A valid test rule.

    Args:
        **campos: Sobrescreve os padroes.

    Returns:
        A regra.
    """
    padroes = {
        "identificador": "teste",
        "sentido": ENTRADA,
        "origem": "10.0.0.0/24",
        "destino": "10.0.0.0/24",
        "acao": PERMITIR,
        "campo": NOVO,
    }
    padroes.update(campos)
    return Regra(**padroes)


class TestRegraCasa:
    """O casamento de trafego com regra: todos os criterios, sempre."""

    def test_tudo_casa(self) -> None:
        regra = regra_base(portas=(443,), protocolo="tcp")
        assert regra.casa(ENTRADA, "10.0.0.5", "10.0.0.9", 443, "tcp", NOVO) is True

    def test_sentido_diferente_nao_casa(self) -> None:
        assert regra_base().casa(
            "saida", "10.0.0.5", "10.0.0.9", 80, "tcp", NOVO
        ) is False

    def test_origem_fora_nao_casa(self) -> None:
        assert regra_base().casa(
            ENTRADA, "192.168.1.1", "10.0.0.9", 80, "tcp", NOVO
        ) is False

    def test_destino_fora_nao_casa(self) -> None:
        assert regra_base().casa(
            ENTRADA, "10.0.0.5", "172.16.0.1", 80, "tcp", NOVO
        ) is False

    def test_porta_fora_nao_casa(self) -> None:
        regra = regra_base(portas=(443,))
        assert regra.casa(ENTRADA, "10.0.0.5", "10.0.0.9", 80, "tcp", NOVO) is False

    def test_sem_portas_casa_qualquer_uma(self) -> None:
        assert regra_base().casa(
            ENTRADA, "10.0.0.5", "10.0.0.9", 9999, "tcp", NOVO
        ) is True

    def test_protocolo_casa(self) -> None:
        regra = regra_base(protocolo="udp")
        assert regra.casa(ENTRADA, "10.0.0.5", "10.0.0.9", 53, "udp", NOVO) is True
        assert regra.casa(ENTRADA, "10.0.0.5", "10.0.0.9", 53, "tcp", NOVO) is False

    def test_protocolo_qualquer_casa_tudo(self) -> None:
        regra = regra_base(protocolo="qualquer")
        assert regra.casa(ENTRADA, "10.0.0.5", "10.0.0.9", 53, "udp", NOVO) is True
        assert regra.casa(ENTRADA, "10.0.0.5", "10.0.0.9", 80, "tcp", NOVO) is True

    def test_campo_tem_de_casar(self) -> None:
        regra = regra_base(campo="relacionado")
        assert regra.casa(ENTRADA, "10.0.0.5", "10.0.0.9", 80, "tcp", "relacionado") is True
        assert regra.casa(ENTRADA, "10.0.0.5", "10.0.0.9", 80, "tcp", NOVO) is False

    def test_endereco_invalido_nao_casa(self) -> None:
        assert regra_base().casa(
            ENTRADA, "nao-e-ip", "10.0.0.9", 80, "tcp", NOVO
        ) is False

    def test_casa_um_de_cada_vez(self) -> None:
        # A regra usa AND em todos os criterios. Uma casa por OR seria uma
        # regra que permite demais - e nao uma regra flexivel.
        regra = regra_base(portas=(443,))
        assert regra.casa(ENTRADA, "10.0.0.5", "10.0.0.9", 22, "tcp", NOVO) is False


class TestRegraInvalida:
    """O construtor recusa o que nao faz sentido."""

    def test_sentido_invalido(self) -> None:
        with pytest.raises(modulo_regras.ErroDeRegra):
            regra_base(sentido="diagonal")

    def test_acao_invalida(self) -> None:
        with pytest.raises(modulo_regras.ErroDeRegra):
            regra_base(acao="talvez")

    def test_protocolo_invalido(self) -> None:
        with pytest.raises(modulo_regras.ErroDeRegra):
            regra_base(protocolo="icmp")

    def test_campo_invalido(self) -> None:
        with pytest.raises(modulo_regras.ErroDeRegra):
            regra_base(campo="futuro")

    def test_porta_fora_da_faixa(self) -> None:
        with pytest.raises(modulo_regras.ErroDeRegra):
            regra_base(portas=(0,))
        with pytest.raises(modulo_regras.ErroDeRegra):
            regra_base(portas=(70000,))

    def test_sem_identificador(self) -> None:
        with pytest.raises(modulo_regras.ErroDeRegra):
            regra_base(identificador="  ")

    def test_str_da_regra(self) -> None:
        regra = regra_base(identificador="minha", portas=(80, 443))
        texto = str(regra)
        assert "minha" in texto
        assert "80" in texto and "443" in texto


class TestTabela:
    """A tabela ordenada e o que ela garante."""

    def test_por_sentido(self, tabela) -> None:
        for regra in tabela.por_sentido("entrada"):
            assert regra.sentido == "entrada"

    def test_por_identificador(self, tabela) -> None:
        assert tabela.por_identificador("internet-entra-no-banco") is not None
        assert tabela.por_identificador("nao-existe") is None

    def test_identificador_repetido(self) -> None:
        tabela = TabelaDeRegras(
            regras=(regra_base(identificador="x"), regra_base(identificador="x"))
        )
        with pytest.raises(modulo_regras.ErroDeRegra):
            tabela.validar()

    def test_ordem_do_arquivo_e_ordem_de_avaliacao(self, tabela) -> None:
        # A ordem nao e detalhe de leitura: e a politica. Este teste prende a
        # ordem das cinco primeiras regras para que uma reordenacao explicita
        # atualize o teste, e nao passe despercebida.
        identificadores = [r.identificador for r in tabela.regras]
        assert identificadores.index("internet-entra-no-balancer") == 0
        assert (
            identificadores.index("internet-entra-no-banco")
            < identificadores.index("nega-o-que-nada-permite")
        )
        assert identificadores[-1] == "nega-o-que-nada-permite"

    def test_o_limite_final_nega_tudo(self, tabela) -> None:
        final = tabela.regras[-1]
        assert final.acao == "negar"
        assert final.origem == "0.0.0.0/0"
        assert final.destino == "0.0.0.0/0"

    def test_a_tabela_tem_dezessete_regras(self, tabela) -> None:
        # Dezesseis originais menos a resposta explicita, que foi removida por
        # permitir trafego falsificado sem estado. Se o numero mudar sem que o
        # teste seja atualizado, a tabela mudou - e e isso que o teste quer
        # pegar.
        assert len(tabela) == 17, [r.identificador for r in tabela.regras]


class TestCargaDeRegras:
    """A leitura do YAML de regras."""

    def test_arquivo_inexistente(self, tmp_path: Path) -> None:
        with pytest.raises(modulo_regras.ErroDeRegra):
            modulo_regras.carregar(tmp_path / "nao-existe.yaml")

    def test_yaml_invalido(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "ruim.yaml"
        arquivo.write_text("regras: [", encoding="utf-8")
        with pytest.raises(modulo_regras.ErroDeRegra):
            modulo_regras.carregar(arquivo)

    def test_topo_nao_e_mapa(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "lista.yaml"
        arquivo.write_text("- a\n", encoding="utf-8")
        with pytest.raises(modulo_regras.ErroDeRegra):
            modulo_regras.carregar(arquivo)


class TestTracador:
    """O tracado mostra o caminho e a regra que decidiu."""

    def _traco(self, tabela, arquitetura, **campos):
        from vpcsim.tracador import tracar

        padroes = {
            "origem": "203.0.113.50", "destino": "10.30.0.11", "porta": 5432,
            "protocolo": "tcp", "sentido": "entrada", "id": "t1",
        }
        padroes.update(campos)
        return tracar(Conexao(**padroes), tabela, arquitetura)

    def test_passos_na_ordem(self, tabela, arquitetura) -> None:
        traco = self._traco(tabela, arquitetura)
        etapas = [p.etapa for p in traco.passos]
        assert etapas[0] == "origem"
        assert "rota" in etapas
        assert "avaliacao" in etapas
        assert etapas[-1] == "regra"

    def test_tracado_cita_a_regra(self, tabela, arquitetura) -> None:
        traco = self._traco(tabela, arquitetura)
        assert traco.decisao.regra is not None
        assert traco.decisao.regra.identificador == "internet-entra-no-banco"

    def test_origem_anonima_quando_nao_e_no(self, tabela, arquitetura) -> None:
        traco = self._traco(tabela, arquitetura)
        origem = traco.passos[0]
        assert "anonima" in origem.detalhe
        assert "203.0.113.50" in origem.detalhe

    def test_destino_resolvido_quando_e_no(self, tabela, arquitetura) -> None:
        traco = self._traco(tabela, arquitetura)
        destino = traco.passos[1]
        assert "banco-01" in destino.detalhe

    def test_formatar_tem_veredito_em_maiusculas(self, tabela, arquitetura) -> None:
        from vpcsim.tracador import formatar

        assert "VEREDITO: BLOQUEADO" in formatar(self._traco(tabela, arquitetura))

    def test_tracado_permitido(self, tabela, arquitetura) -> None:
        from vpcsim.tracador import formatar

        traco = self._traco(
            tabela, arquitetura,
            origem="10.20.0.11", destino="10.30.0.11", id="t2",
        )
        assert "VEREDITO: PERMITIDO" in formatar(traco)
        assert traco.decisao.regra.identificador == "aplicacao-entra-no-banco"
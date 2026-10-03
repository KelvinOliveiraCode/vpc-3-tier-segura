"""Testes dos cenarios e da linha de comando.

Scenario and CLI tests.

Os cenarios sao dado de teste, e dado de teste tem exigencias que codigo nao
tem: cada um precisa de um resultado esperado, e ids repetidos precisam ser
erro. O CLI e a superficie que o usuario ve, e o que ele precisa garantir e o
codigo de saida - um portao que reporta divergencia e devolve zero e pior do
que um portao sem estagios.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

import pytest

from vpcsim import cenarios as modulo_cenarios
from vpcsim.cenarios import BLOQUEADO, PERMITIDO, Cenario, carregar
from vpcsim.cli import main as cli_main

RAIZ = Path(__file__).resolve().parent.parent
CENARIOS = RAIZ / "dados" / "cenarios-teste.yaml"


@pytest.fixture(scope="module")
def casos():
    return carregar(CENARIOS)


class TestCarga:
    """A leitura do YAML de cenarios."""

    def test_vinte_cenarios(self, casos) -> None:
        assert len(casos) == TOTAL_ESPERADO_CENARIOS

    def test_todo_cenario_tem_resultado_esperado(self, casos) -> None:
        for caso in casos:
            assert caso.esperado in (PERMITIDO, BLOQUEADO), caso.id

    def test_ids_unicos(self, casos) -> None:
        ids = [c.id for c in casos]
        assert len(ids) == len(set(ids))

    def test_ha_permitidos_e_bloqueados(self, casos) -> None:
        resultados = {c.esperado for c in casos}
        assert resultados == {PERMITIDO, BLOQUEADO}

    def test_todos_os_campos_tem_representante(self, casos) -> None:
        campos = {c.campo for c in casos}
        assert campos == {"novo", "relacionado", "estabelecido"}, campos

    def test_tem_entrada_e_saida(self, casos) -> None:
        sentidos = {c.sentido for c in casos}
        assert sentidos == {"entrada", "saida"}, sentidos

    def test_todo_porque_e_especifico(self, casos) -> None:
        porques = [c.porque for c in casos]
        assert all(porques), "cenario sem porque"
        assert len(set(porques)) == len(porques), "porque repetido"

    def test_arquivo_inexistente(self, tmp_path: Path) -> None:
        with pytest.raises(modulo_cenarios.ErroDeCenario):
            carregar(tmp_path / "nao-existe.yaml")

    def test_yaml_invalido(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "ruim.yaml"
        arquivo.write_text("cenarios: [", encoding="utf-8")
        with pytest.raises(modulo_cenarios.ErroDeCenario):
            carregar(arquivo)

    def test_cenario_incompleto(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "falta.yaml"
        arquivo.write_text("cenarios:\n  - id: x\n", encoding="utf-8")
        with pytest.raises(modulo_cenarios.ErroDeCenario):
            carregar(arquivo)

    def test_id_repetido(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "repetido.yaml"
        arquivo.write_text(
            "cenarios:\n"
            "  - id: x\n    origem: 10.0.0.1\n    destino: 10.0.0.2\n"
            "    porta: 80\n    protocolo: tcp\n    sentido: entrada\n"
            "    esperado: permitido\n"
            "  - id: x\n    origem: 10.0.0.1\n    destino: 10.0.0.2\n"
            "    porta: 80\n    protocolo: tcp\n    sentido: entrada\n"
            "    esperado: permitido\n",
            encoding="utf-8",
        )
        with pytest.raises(modulo_cenarios.ErroDeCenario):
            carregar(arquivo)

    def test_porta_invalida(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "porta.yaml"
        arquivo.write_text(
            "cenarios:\n  - id: x\n    origem: 10.0.0.1\n    destino: 10.0.0.2\n"
            "    porta: 99999\n    protocolo: tcp\n    sentido: entrada\n"
            "    esperado: permitido\n",
            encoding="utf-8",
        )
        with pytest.raises(modulo_cenarios.ErroDeCenario):
            carregar(arquivo)


TOTAL_ESPERADO_CENARIOS = 20


class TestCli:
    """A linha de comando e o codigo de saida."""

    def _roda(self, argv):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            codigo = cli_main(argv)
        return codigo, buffer.getvalue()

    def test_cenarios_todos_ok_saida_zero(self) -> None:
        assert self._roda(["cenarios"])[0] == 0

    def test_tracar_todos_ok_saida_zero(self, tmp_path: Path) -> None:
        destino = tmp_path / "tracos.txt"
        codigo, _ = self._roda(["tracar", "--saida", str(destino)])
        assert codigo == 0
        assert destino.exists()

    def test_tracar_escreve_o_arquivo(self, tmp_path: Path) -> None:
        destino = tmp_path / "tracos.txt"
        self._roda(["tracar", "--saida", str(destino)])
        texto = destino.read_text(encoding="utf-8")
        assert "internet-para-banco" in texto
        assert "VEREDITO" in texto

    def test_regras_lista_as_dezessete(self) -> None:
        codigo, saida = self._roda(["regras"])
        assert codigo == 0
        assert "17 regra(s)" in saida

    def test_arquitetura_mostra_as_camadas(self) -> None:
        codigo, saida = self._roda(["arquitetura"])
        assert codigo == 0
        for camada in ("DMZ", "APLICACAO", "DADOS"):
            assert camada in saida

    def test_arquivo_inexistente_saida_dois(self, tmp_path: Path) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            codigo = cli_main(["cenarios", str(tmp_path / "nao-existe.yaml")])
        assert codigo == 2

    def test_help_sai_com_zero(self) -> None:
        with pytest.raises(SystemExit) as erro:
            cli_main(["--help"])
        assert erro.value.code == 0

    def test_help_de_cada_comando(self) -> None:
        for comando in ("tracar", "cenarios", "regras", "arquitetura"):
            with pytest.raises(SystemExit) as erro:
                cli_main([comando, "--help"])
            assert erro.value.code == 0

    def test_sem_comando_falha(self) -> None:
        with pytest.raises(SystemExit):
            cli_main([])

    def test_divergencia_da_saida_um(self, tmp_path: Path) -> None:
        # Um cenario cujo esperado contradiz o motor tem de fazer o comando
        # sair com 1. Sem isso o job de CI passa com o motor errado.
        arquivo = tmp_path / "mentiroso.yaml"
        arquivo.write_text(
            'cenarios:\n  - id: mentiroso\n    origem: "203.0.113.50"\n'
            '    destino: "10.30.0.11"\n    porta: 5432\n    protocolo: tcp\n'
            "    sentido: entrada\n    esperado: permitido\n",
            encoding="utf-8",
        )
        codigo, saida = self._roda(["cenarios", str(arquivo)])
        assert codigo == 1
        assert "DIVERGIU" in saida
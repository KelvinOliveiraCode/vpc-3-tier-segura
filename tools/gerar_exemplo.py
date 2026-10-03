"""Gera o exemplo de tracos de trafego a partir da saida real.

Generate the traffic-trace example from the real output.

O exemplo vai para o repositorio para ser lido sem instalar nada, e por isso
precisa ser a saida de verdade e nao uma transcricao. Se for transcricao, o
codigo muda, o exemplo nao, e o exemplo passa a descrever um motor que nao
existe mais.

Por isso o exemplo e GERADO pelo proprio `tracar`, com os caminhos reais do
projeto, e o CI compara o arquivo do repositorio com o que este script produz.
Divergencia derruba o build.

Nao ha timestamp nem caminho absoluto em nada aqui, para que o arquivo seja
identico em qualquer maquina.
"""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from vpcsim.cli import main as cli_main  # noqa: E402

CENARIOS = "dados/cenarios-teste.yaml"
DESTINO = RAIZ / "exemplos" / "tracos-de-trafego.txt"


def principal() -> int:
    """Regera o exemplo e grava no destino.

    Regenerate the example and write it to the destination.

    Returns:
        O codigo de saida do `tracar`, ou 1 se divergiu.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        codigo = cli_main(["tracar", CENARIOS, "--saida", str(DESTINO)])

    cabecalho = [
        "# Tracos de trafego do vpcsim.",
        "#",
        "# Este arquivo e GERADO por tools/gerar_exemplo.py, a partir da saida",
        "# real do comando `python -m vpcsim tracar`. Nao editar a mao.",
        "#",
        "# Para reproduzir localmente:",
        "#",
        "#   python -m vpcsim tracar dados/cenarios-teste.yaml",
        "#",
    ]
    conteudo = DESTINO.read_text(encoding="utf-8")
    DESTINO.write_text(
        "\n".join(cabecalho) + "\n\n" + conteudo, encoding="utf-8", newline="\n"
    )
    print(f"exemplo gravado em {DESTINO.relative_to(RAIZ)}")
    return codigo


if __name__ == "__main__":
    raise SystemExit(principal())
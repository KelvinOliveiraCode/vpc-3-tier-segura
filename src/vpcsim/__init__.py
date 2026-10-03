"""vpcsim - simulador local de VPC com motor de firewall.

vpcsim - local VPC simulator with a firewall decision engine.

Uma VPC de tres camadas, com regras de seguranca e um motor que **avalia**
qual trafego e permitido e em qual regra a decisao foi tomada. Nada aqui
acessa nuvem: as camadas sao simuladas em codigo, o que e o unico jeito de
demonstrar o conceito sem custo e sem credencial.

O ponto do projeto nao e o desenho das regras, e o **motor**. Uma regra de
firewall se escreve em cinco minutos e se erra em cinco minutos; o que ensina
e construir o motor, avaliar milhares de combinacoes e ver o resultado mudar
quando uma regra se move de lugar.
"""

from __future__ import annotations

__version__ = "1.0.0"

__all__ = ["__version__"]
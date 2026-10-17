<img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python">
<img src="https://img.shields.io/badge/testes-105%20passando-brightgreen?style=flat-square" alt="Testes">
<img src="https://img.shields.io/badge/cobertura-90%25-green?style=flat-square" alt="Cobertura">
<img src="https://img.shields.io/badge/dependencias-PyYAML%20apenas-blue?style=flat-square" alt="Dependencias">
<img src="https://img.shields.io/badge/licenca-MIT-yellow?style=flat-square" alt="Licenca">
<img src="https://img.shields.io/badge/plataforma-Windows-blue?style=flat-square" alt="Windows">

# vpc-3-tier-segura

Simulador local de uma VPC em tres camadas com motor de firewall: avalia qual trafego e permitido e mostra em qual regra a decisao foi tomada. Nada acessa nuvem; as camadas sao simuladas em codigo.

## Problema / Por que existe

Uma regra de firewall se escreve em cinco minutos e se erra em cinco minutos. O que ensina e construir o motor, avaliar combinacoes e ver o resultado mudar quando uma regra se move de lugar. Quem opera infraestrutura precisa de uma maquina que diga o que passa, o que nao passa e por qual regra.

Este projeto existe para demonstrar isso: um simulador local de VPC de tres camadas com regras de seguranca e um motor que avalia cada pacote contra a topologia e a tabela de regras, sem depender de credencial, conta de nuvem ou rede real.

## O que faz

- Carrega a arquitetura, as regras e os cenarios de arquivos YAML em `dados/`.
- Modela cinco camadas: DMZ, aplicacao, dados, gerencia e parceiro, com sub-redes, nos e tabelas de roteamento.
- Avalia cada pacote em cinco etapas, em ordem fixa: `relacionado`, `sem-rota`, `permitido`, `bloqueado`, `sem-regra`.
- Trata trafego de retorno como estado de conexao, nao como uma regra nova.
- Nega por padrao: quando nenhuma regra casa, o trafego e bloqueado e o motivo fica registrado.
- Mostra, para cada pacote, origem, destino, rota, etapa da decisao e a regra que decidiu.
- Roda em linha de comando com quatro comandos: `cenarios`, `tracar`, `regras` e `arquitetura`.
- Retorna codigo de saida 1 quando algum cenario diverge do esperado, o que serve como portao de CI.

## Stack

- Python 3.10 ou superior. O CI roda no Windows com Python 3.11.
- Unica dependencia de execucao: PyYAML >= 6.0, usada apenas para ler os arquivos YAML. O restante e biblioteca padrao (`ipaddress`, `dataclasses`, `argparse`).
- Dependencias de desenvolvimento: pytest >= 7.4 e pytest-cov >= 4.1.
- Nenhum SDK de nuvem, biblioteca de SSH nem cliente de equipamento de rede.

## Como funciona

A propriedade que o desenho quer tornar verdadeira: o banco nao aceita conexao vinda da internet.

Arquitetura (de `dados/arquitetura.yaml`):

| Camada | Sub-rede | CIDR | Visibilidade | Nos |
|---|---|---|---|---|
| DMZ | dmz-publica | 203.0.113.0/24 | publica | balancer-web, web-publico-01, web-publico-02 |
| Aplicacao | app-privada | 10.20.0.0/24 | privada | app-01, app-02 |
| Dados | dados-privada | 10.30.0.0/24 | privada, sem rota para fora | banco-01 |
| Gerencia | gestao-privada | 10.10.0.0/24 | privada | bastion |
| Parceiro | parceiro-publica | 198.51.100.0/24 | publica, sem rota de saida | web-parceiro |

Os blocos `203.0.113.0/24` (TEST-NET-1) e `198.51.100.0/24` (TEST-NET-2) da RFC 5737 sao reservados a exemplo e nao existem em rota real.

Motor (em `src/vpcsim/firewall.py`), na ordem fixa:

1. `relacionado` — resposta de conexao ja autorizada; passa sem reabrir a tabela. O par de enderecos e procurado nas duas direcoes.
2. `sem-rota` — pacote sem rota de retorno. Nao e bloqueio por politica: simplesmente nao chega.
3. `permitido` — primeira regra da tabela que casa com o pacote.
4. `bloqueado` — uma regra negou explicitamente.
5. `sem-regra` — nenhuma regra casou; o motor nega por padrao.

A ordem e fixa e e a politica: resposta antes da rota, rota antes da tabela. A tabela termina com um `negar` explicito para que o limite esteja escrito no arquivo.

Regras (em `dados/regras.yaml`):

- A primeira regra que casa decide; a ordem no arquivo e parte da politica de seguranca.
- Cada regra tem sentido (`entrada` ou `saida`), origem, destino, portas, protocolo, campo de estado (`novo`, `relacionado`, `estabelecido`), acao (`permitir` ou `negar`) e um campo `motivo` que explica por que existe.
- Trafego de retorno viaja pelo estado da conexao, nao por uma regra nova.

Exemplo de saida de `python -m vpcsim tracar`:

```
[internet-para-banco] 203.0.113.50 -> 10.30.0.11
  origem: origem anonima: 203.0.113.50
  destino: banco-01, 10.30.0.11, sub-rede dados-privada
  rota: rota dmz-publica -> 0.0.0.0/0, proximo salto 203.0.113.1
  avaliacao: etapa bloqueado: A regra que o desenho inteiro existe para
    sustentar: o banco nao aceita conexao da internet...
  regra: negar entrada 203.0.113.0/24 -> 10.30.0.11/32:5432/tcp [novo] #internet-entra-no-banco
VEREDITO: BLOQUEADO
resultado esperado: bloqueado   obtido: bloqueado   [ok]
```

## Como rodar

Instalacao:

```powershell
pip install -e ".[dev]"
```

Rodar os 20 cenarios:

```powershell
python -m vpcsim cenarios
```

Saida esperada:

```
cenario                                        esperado    obtido      veredito
------------------------------------------------------------------------------
internet-para-banco                            bloqueado   bloqueado   ok
bastion-para-banco                             permitido   permitido   ok
app-para-banco                                 permitido   permitido   ok
...
todos os 20 cenarios concordam com o motor
```

Traçar um pacote:

```powershell
python -m vpcsim tracar
```

Outros comandos:

```powershell
python -m vpcsim regras
python -m vpcsim arquitetura
```

Todos os comandos leem `dados/` por caminho padrao e aceitam caminhos alternativos por opcao.

Testes:

```powershell
python -m pytest
```

Resultado verificado neste repositorio: 105 testes passando, cobertura de 90% (limite exigido: 70%).

Portoes adicionais da CI:

```powershell
python tools/verificar_aceite.py
python tools/verificar_encoding.py
python tools/gerar_exemplo.py
```

## Estrutura do projeto

```
vpc-3-tier-segura/
├── src/vpcsim/         # pacote: cli, rede, regras, firewall, tracador, cenarios
├── dados/              # arquitetura.yaml, regras.yaml, cenarios-teste.yaml
├── docs/               # modelo-de-seguranca-em-nuvem.md, principio-de-menor-privilegio.md
├── exemplos/           # tracos-de-trafego.txt (saida do tracador, commitada)
├── tests/              # 105 testes: test_cenarios_cli, test_firewall, test_rede, test_regras_tracador
├── tools/              # corrigir_cenarios, gerar_exemplo, verificar_aceite, verificar_encoding
├── pyproject.toml      # projeto vpcsim 1.0.0, Python >= 3.10, dep PyYAML
├── requirements.txt    # PyYAML e dependencias de desenvolvimento
└── README.md
```

## Trade-offs e decisões

- Modelo que descreve e nao decide: `rede.py` so sabe o que existe; a decisao e do `firewall.py` e a rastreabilidade e do `tracador.py`. Isso evita que ninguem consiga dizer por que o trafego passou sem ler o motor.
- Rota verificada antes da tabela: a DMZ tem rota padrao para a internet, filtrada pela sub-rede de origem, para nao mostrar um proximo salto que nunca seria usado.
- Dois mecanismos protegem o banco: a regra `internet-entra-no-banco` nega, e a camada de dados nao tem rota de retorno para a internet. Qualquer uma sozinha seria insuficiente.
- O padrao e negar: regra esquecida vira acesso negado, visivel e corrigido em um minuto, nao acesso concedido silencioso.
- O estado vem do cenario: as conexoes autorizadas sao declaradas no YAML, nao observadas do trafego. Um motor real construiria a tabela de estado vendo os pacotes.
- Saida de codigo 1 em `cenarios` e `tracar` quando algum cenario diverge, para servir como portao de CI.

## Limitacoes conhecidas

- Simulacao local: nenhum pacote atravessa rede real; o motor prova logica de endereçamento, nao resistencia a ataque.
- Sem inspecao de pacote: avalia origem, destino, porta, protocolo e estado. Nao olha conteudo, fragmentacao nem ordem de chegada.
- ACLs avaliadas globalmente: sem direcao por interface, sem ordem entre ACLs, sem timeout de conexao.
- Topologia fixa: adicionar camada exige editar o YAML e as regras, nao so declarar.
- IPv4 apenas: sem IPv6, sem dual-stack, sem NAT.
- Unica dependencia externa: PyYAML.

## Licenca

MIT. Veja o arquivo `LICENSE`.

## Autor

Kelvin Oliveira

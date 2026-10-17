# vpc-3-tier-segura

<img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python">
<img src="https://img.shields.io/badge/tests-105%20passing-brightgreen?style=flat-square" alt="Tests">
<img src="https://img.shields.io/badge/coverage-90%25-green?style=flat-square" alt="Coverage">
<img src="https://img.shields.io/badge/dependencies-PyYAML%20only-blue?style=flat-square" alt="Dependencies">
<img src="https://img.shields.io/badge/license-MIT-yellow?style=flat-square" alt="License">
<img src="https://img.shields.io/badge/platform-Windows-blue?style=flat-square" alt="Windows">

Local simulator of a three-tier VPC with a firewall engine: evaluates which traffic is allowed and shows which rule made the decision. Nothing accesses the cloud; the tiers are simulated in code.

## Problem / Why it exists

A firewall rule takes five minutes to write and five minutes to get wrong. What teaches is building the engine, evaluating combinations, and watching the result change when a rule moves. Whoever runs infrastructure needs a machine that says what passes, what does not pass, and by which rule.

This project exists to demonstrate that: a local simulator of a three-tier VPC with security rules and an engine that evaluates each packet against the topology and the rule table, without depending on credentials, cloud account, or real network.

## What it does

- Loads architecture, rules, and scenarios from YAML files in `dados/`.
- Models five tiers: DMZ, application, data, management, and partner, with subnets, nodes, and routing tables.
- Evaluates each packet in five fixed steps: `related`, `no-route`, `allowed`, `blocked`, `no-rule`.
- Treats return traffic as connection state, not as a new rule.
- Denies by default: when no rule matches, traffic is blocked and the reason is recorded.
- Shows, for each packet, source, destination, route, decision step, and the rule that decided.
- Runs from the command line with four commands: `cenarios`, `tracar`, `regras`, and `arquitetura`.
- Returns exit code 1 when some scenario diverges from expected, which serves as a CI gate.

## Stack

- Python 3.10 or higher. CI runs on Windows with Python 3.11.
- Only runtime dependency: PyYAML >= 6.0, used only to read the YAML files. The rest is standard library (`ipaddress`, `dataclasses`, `argparse`).
- Development dependencies: pytest >= 7.4 and pytest-cov >= 4.1.
- No cloud SDK, SSH library, or network equipment client.

## How it works

The property the design wants to make true: the database does not accept connections from the internet.

Architecture (from `dados/arquitetura.yaml`):

| Tier | Subnet | CIDR | Visibility | Nodes |
|---|---|---|---|---|
| DMZ | dmz-publica | 203.0.113.0/24 | public | balancer-web, web-publico-01, web-publico-02 |
| Application | app-privada | 10.20.0.0/24 | private | app-01, app-02 |
| Data | dados-privada | 10.30.0.0/24 | private, no route out | banco-01 |
| Management | gestao-privada | 10.10.0.0/24 | private | bastion |
| Partner | parceiro-publica | 198.51.100.0/24 | public, no outbound route | web-parceiro |

The blocks `203.0.113.0/24` (TEST-NET-1) and `198.51.100.0/24` (TEST-NET-2) from RFC 5737 are reserved for examples and do not exist in real routing.

Engine (in `src/vpcsim/firewall.py`), in fixed order:

1. `related` — response of an already authorized connection; passes without reopening the table. The address pair is searched in both directions.
2. `no-route` — packet with no return route. Not a policy block: it simply does not arrive.
3. `allowed` — first rule in the table that matches the packet.
4. `blocked` — a rule explicitly denied.
5. `no-rule` — no rule matched; the engine denies by default.

The order is fixed and is the policy: response before route, route before table. The table ends with an explicit `deny` so the limit is written in the file.

Rules (in `dados/regras.yaml`):

- The first matching rule decides; the order in the file is part of the security policy.
- Each rule has direction (`entrada` or `saida`), source, destination, ports, protocol, state field (`novo`, `relacionado`, `estabelecido`), action (`permitir` or `negar`), and a `motivo` field explaining why it exists.
- Return traffic travels through connection state, not through a new rule.

Example output of `python -m vpcsim tracar`:

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

## How to run

Installation:

```powershell
pip install -e ".[dev]"
```

Run the 20 scenarios:

```powershell
python -m vpcsim cenarios
```

Expected output:

```
cenario                                        esperado    obtido      veredito
------------------------------------------------------------------------------
internet-para-banco                            bloqueado   bloqueado   ok
bastion-para-banco                             permitido   permitido   ok
app-para-banco                                 permitido   permitido   ok
...
todos os 20 cenarios concordam com o motor
```

Trace a packet:

```powershell
python -m vpcsim tracar
```

Other commands:

```powershell
python -m vpcsim regras
python -m vpcsim arquitetura
```

All commands read `dados/` by default and accept alternative paths by option.

Tests:

```powershell
python -m pytest
```

Verified result in this repository: 105 tests passing, 90 percent coverage (required floor: 70 percent).

Additional CI gates:

```powershell
python tools/verificar_aceite.py
python tools/verificar_encoding.py
python tools/gerar_exemplo.py
```

## Project structure

```
vpc-3-tier-segura/
├── src/vpcsim/         # package: cli, rede, regras, firewall, tracador, cenarios
├── dados/              # arquitetura.yaml, regras.yaml, cenarios-teste.yaml
├── docs/               # modelo-de-seguranca-em-nuvem.md, principio-de-menor-privilegio.md
├── exemplos/           # tracos-de-trafego.txt (tracer output, committed)
├── tests/              # 105 tests: test_cenarios_cli, test_firewall, test_rede, test_regras_tracador
├── tools/              # corrigir_cenarios, gerar_exemplo, verificar_aceite, verificar_encoding
├── pyproject.toml      # project vpcsim 1.0.0, Python >= 3.10, PyYAML dep
├── requirements.txt    # PyYAML and development dependencies
└── README.md
```

## Trade-offs and decisions

- Model that describes, not decides: `rede.py` only knows what exists; the decision belongs to `firewall.py` and traceability to `tracador.py`. That prevents anyone from saying why traffic passed without reading the engine.
- Route verified before the table: the DMZ has a default route to the internet, filtered by source subnet, so it never shows a next hop that would never be used.
- Two mechanisms protect the database: the `internet-entra-no-banco` rule denies, and the data tier has no return route to the internet. Either alone would be insufficient.
- Default is deny: a forgotten rule becomes denied access, visible and fixed in one minute, not silent granted access.
- State comes from the scenario: authorized connections are declared in the YAML, not observed from traffic. A real engine would build the state table by watching packets.
- Exit code 1 in `cenarios` and `tracar` when some scenario diverges, to serve as a CI gate.

## Known limitations

- Local simulation: no real packet crosses a real network; the engine proves addressing logic, not resistance to attack.
- No packet inspection: evaluates source, destination, port, protocol, and state. Does not look at content, fragmentation, or arrival order.
- ACLs evaluated globally: no direction per interface, no ordering between ACLs, no connection timeout.
- Fixed topology: adding a tier requires editing the YAML and the rules, not just declaring.
- IPv4 only: no IPv6, no dual-stack, no NAT.
- Single external dependency: PyYAML.

## License

MIT. See the `LICENSE` file.

## Author

Kelvin Oliveira
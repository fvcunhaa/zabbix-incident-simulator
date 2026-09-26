# Zabbix Incident Simulator

Simulador leve de incidentes para Zabbix 7.0+, criado para gerar massa de dados realista para fluxos Zabbix -> GLPI -> indicadores/IA.

## O que a V1 faz

- Cria automaticamente aproximadamente 200 hosts (20 clientes x 10 ativos por padrão).
- Cria itens Zabbix Trapper e triggers de simulação.
- Gera aproximadamente 20 novos incidentes por hora com intervalos variáveis.
- Usa `history.push` para provocar PROBLEM e Recovery de forma natural.
- Realiza ACK entre 3 e 25 minutos.
- Insere uma tratativa intermediária.
- Resolve o problema entre 30 e 180 minutos.
- Mantém estado em SQLite para suportar restart do container.
- Permite disparar incidentes manualmente por API.

## Inventário padrão

Por cliente, 10 hosts:

- 5 servidores
- 1 banco
- 2 switches
- 1 firewall
- 1 web/application

Com 20 clientes = 200 hosts.

Exemplos:

- `CLIENTE-01-SRV-001`
- `CLIENTE-01-DB-001`
- `CLIENTE-01-SW-001`
- `CLIENTE-01-FW-001`
- `CLIENTE-01-WEB-001`

## Cenários

- CPU alta
- Memória alta
- Filesystem crítico
- Serviço parado
- Host indisponível
- Latência alta
- Packet loss

Os cenários e as mensagens de ACK/tratativa/solução estão em `config/scenarios.yaml` e podem ser alterados sem modificar o motor Python.

## Pré-requisitos no Zabbix

Crie um API token de um usuário com permissões para:

- criar/ler host groups;
- criar/ler hosts;
- criar/ler items;
- criar/ler triggers;
- usar `history.push`;
- ler events;
- usar `event.acknowledge`.

> `history.push` exige que o endereço do frontend Zabbix esteja aceito no campo **Allowed hosts** dos itens trapper. No LAB este projeto usa `ZABBIX_TRAPPER_ALLOWED_HOSTS=0.0.0.0/0` por padrão no exemplo. Restrinja isso fora de laboratório.

## Subir

```bash
cp .env.example .env
nano .env

docker compose up -d --build

docker logs -f zabbix-incident-simulator
```

Na primeira inicialização, o container tenta executar o bootstrap automaticamente.

## Endpoints

### Health

```bash
curl http://localhost:8080/health
```

### Status

```bash
curl http://localhost:8080/status
```

### Reexecutar bootstrap

```bash
curl -X POST http://localhost:8080/bootstrap \
  -H 'X-API-Key: change-me'
```

### Iniciar geração automática

```bash
curl -X POST http://localhost:8080/simulation/start \
  -H 'X-API-Key: change-me'
```

### Parar geração automática

```bash
curl -X POST http://localhost:8080/simulation/stop \
  -H 'X-API-Key: change-me'
```

### Gerar incidente aleatório imediatamente

```bash
curl -X POST http://localhost:8080/incident/generate \
  -H 'X-API-Key: change-me' \
  -H 'Content-Type: application/json' \
  -d '{}'
```

### Forçar cenário

```bash
curl -X POST http://localhost:8080/incident/generate \
  -H 'X-API-Key: change-me' \
  -H 'Content-Type: application/json' \
  -d '{"scenario":"disk_full"}'
```

### Forçar host + cenário

```bash
curl -X POST http://localhost:8080/incident/generate \
  -H 'X-API-Key: change-me' \
  -H 'Content-Type: application/json' \
  -d '{"host":"CLIENTE-01-SRV-001","scenario":"disk_full"}'
```

### Incidentes

```bash
curl 'http://localhost:8080/incidents?limit=100'
curl 'http://localhost:8080/incidents?active=true'
```

## Linha do tempo criada

Exemplo:

```text
14:00  PROBLEM gerado no Zabbix
14:11  ACK + comentário do analista
14:42  comentário de tratativa
15:26  comentário de solução
15:26  valor normal enviado -> Recovery no Zabbix
```

As faixas são parametrizadas no `.env`:

```env
ACK_MIN_MINUTES=3
ACK_MAX_MINUTES=25
RESOLUTION_MIN_MINUTES=30
RESOLUTION_MAX_MINUTES=180
```

## Indicadores futuros

A base já registra:

- `opened_at`
- `ack_at`
- `treatment_at`
- `resolved_at`
- cliente
- host
- tipo do ativo
- cenário
- analista
- Zabbix `eventid`

Isso deixa a V1 preparada para os próximos passos: GLPI, MTTA, MTTR, TTO/TTS, SLA, escalonamento N1/N2, reincidência e análise por IA.

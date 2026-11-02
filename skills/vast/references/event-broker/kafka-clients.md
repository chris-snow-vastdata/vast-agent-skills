# Kafka clients against VAST Event Broker

VAST implements a subset of the Kafka protocol (KB 5.5 "Kafka Protocol Support"). Use
standard clients with VAST-safe settings. Supported client per KB 5.5: **Confluent Kafka Python
2.4-2.8** (`pip install "confluent-kafka>=2.4,<2.9"`); the KB examples also use `kafka-python`;
**aiokafka is not supported**. Other clients (Java, Go, librdkafka-based tools, Kafka Connect)
speak the same protocol but aren't on the KB list: test them, and apply the same settings.
Option names below are the clients' own (librdkafka / Java); check the client's docs for its version.

## Settings every client needs

| Setting | Value | Why |
|---|---|---|
| `bootstrap.servers` | `<vip1>:<port>,<vip2>:<port>,<vip3>:<port>` | KB: three VIPs of the broker view's Kafka pool. Ports in the Web UI: 9092 plaintext, 9093 TLS. |
| `compression.type` | `none` | No over-the-wire compression. |
| `enable.idempotence` | `false` | Idempotent producing unsupported (Java ≥3.0 defaults to true). |
| (no) `transactional.id` / `isolation.level=read_uncommitted` | — | No transactions; READ UNCOMMITTED unsupported. |
| `partition.assignment.strategy` | `range` or `roundrobin` | Cooperative rebalancing unsupported. |
| (no) `group.instance.id` | — | Static membership unsupported. |
| `allow.auto.create.topics` | irrelevant | Topics must exist. |
| message size | ≤1MB; key ≤126KB; value ≤126KB | KB limits. |

## Security settings

| Broker view setting (5.5) | Client settings |
|---|---|
| plaintext, no auth | `security.protocol=PLAINTEXT` |
| plaintext + SASL/PLAIN | `security.protocol=SASL_PLAINTEXT`, `sasl.mechanism(s)=PLAIN`, `sasl.username`, `sasl.password` |
| TLS, no auth | `security.protocol=SSL`, `ssl.ca.location=<internal-CA.pem>` |
| TLS + SASL/PLAIN | `security.protocol=SASL_SSL` + the SASL and CA settings |
| mTLS | `security.protocol=SSL`, `ssl.ca.location`, `ssl.certificate.location`, `ssl.key.location` (TLS 1.3) |

SASL users are VAST **local** users of the tenant's provider (KB). Which credential the
password field takes isn't spelled out in the pages read for this guide: check the release's
KB "Configuring User Authentication for the VAST Event Broker View" before telling the user.
Keep credentials out of committed files (environment variables or a secrets store).

Check the TLS certificate from a client: `openssl s_client -connect <vip>:<tls-port> -showcerts`
(SANs must contain the VIP IPs).

## confluent-kafka (Python)

```python
import os
from confluent_kafka import Producer, Consumer
from confluent_kafka.admin import AdminClient, NewTopic

conf = {
    "bootstrap.servers": os.environ["VAST_KAFKA_BOOTSTRAP"],   # "<vip1>:9092,<vip2>:9092,<vip3>:9092"
    # "security.protocol": "SASL_SSL", "sasl.mechanisms": "PLAIN",
    # "sasl.username": os.environ["VAST_KAFKA_USER"], "sasl.password": os.environ["VAST_KAFKA_PASSWORD"],
    # "ssl.ca.location": "/path/to/internal-ca.pem",
}

admin = AdminClient(conf)
print(sorted(admin.list_topics(timeout=10).topics))           # connectivity check
fut = admin.create_topics([NewTopic("<topic>", num_partitions=<n>, replication_factor=1)])
for t, f in fut.items(): f.result()                            # raises on error

p = Producer({**conf, "compression.type": "none", "enable.idempotence": False, "acks": "all"})
def report(err, msg):
    if err: print("delivery failed:", err)
for i in range(10):
    p.produce("<topic>", key=str(i).encode(), value=b'{"n": %d}' % i, on_delivery=report)
p.flush(30)

c = Consumer({**conf, "group.id": "<group>", "auto.offset.reset": "earliest",
              "partition.assignment.strategy": "range"})
c.subscribe(["<topic>"])
try:
    while True:
        m = c.poll(1.0)
        if m is None: continue
        if m.error(): print(m.error()); continue
        print(m.partition(), m.offset(), m.key(), m.value())
finally:
    c.close()
```

## kafka-python (as in the KB examples)

```python
from kafka import KafkaProducer, KafkaConsumer
from kafka.admin import KafkaAdminClient, NewTopic
BOOT = ["<vip1>:9092", "<vip2>:9092", "<vip3>:9092"]
KafkaAdminClient(bootstrap_servers=BOOT).create_topics(
    [NewTopic(name="<topic>", num_partitions=<n>, replication_factor=1)])
prod = KafkaProducer(bootstrap_servers=BOOT)          # compression_type defaults to None
prod.send("<topic>", key=b"k", value=b"v"); prod.flush()
for msg in KafkaConsumer("<topic>", bootstrap_servers=BOOT,
                         auto_offset_reset="earliest", group_id="<group>"):
    print(msg.value)
```

## Command-line tools

`kcat` (librdkafka) works for quick checks: `kcat -b <vip>:9092 -L` (metadata),
`kcat -b <vip>:9092 -t <topic> -C -o beginning -e` (consume). Pass `-X compression.codec=none`
when producing. Apache Kafka's `kafka-*.sh` tools are Java clients: set
`enable.idempotence=false` in the producer config.

## Topic configuration through the Admin API

Supported (KB): create, delete, `describeConfigs`, `alterConfigs`, delete consumer groups. Topic
config names match VMS fields: `retention.ms`, `cleanup.policy`, `min.compaction.lag.ms`,
`delete.retention.ms`, `message.timestamp.type`, `message.timestamp.before.max.ms`,
`message.timestamp.after.max.ms`, `max.message.bytes` (Kafka spellings of the VMS names; verify
with `describe_configs` on the user's cluster). Partitions can't be changed after creation.

## Benchmarking

KB "Kafka Performance Benchmarking with OpenMessaging Framework" runs OpenMessaging Benchmark with
VAST-friendly settings (`compression.type=none`, `enable.idempotence=false`).

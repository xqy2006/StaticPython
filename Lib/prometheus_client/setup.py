from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="prometheus_client",
    project_name="prometheus-client",
    overlay_entries=["Lib/prometheus_client"],
    verification_steps=[
        inline_verification_step(
            "prometheus-client-smoke",
            """
from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest

registry = CollectorRegistry()
counter = Counter("staticpython_requests_total", "StaticPython requests", registry=registry)
gauge = Gauge("staticpython_queue_depth", "StaticPython queue depth", registry=registry)

counter.inc()
counter.inc(2)
gauge.set(7)

payload = generate_latest(registry).decode("utf-8")
assert "staticpython_requests_total 3.0" in payload
assert "staticpython_queue_depth 7.0" in payload
""",
        )
    ],
)

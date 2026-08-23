"""
Smoke Test Scenario - minimal end-to-end sanity check.

Sends a small number of requests (default 3) to known-good services and
reports a clear PASS/FAIL against the LB acceptance rate.  Scheduler-side
job outcome check is done in the playbook via tight poll + enrich.

Known-good services: 13, 14, 17.  Services 19/20/24/25 (thumbnailer,
compression, dna-visualisation, graph-bfs) are stdout-based containers with
no HTTP server; provider1.py now handles them gracefully but they remain
excluded from the smoke set until verified in a full run.
"""
import asyncio
from scenarios.base_scenario import BaseScenario
from core.load_balancer_client import LoadBalancerClient

_SMOKE_SERVICES = [13, 14, 17]
_SEND_INTERVAL_S = 0.5


class SmokeTestScenario(BaseScenario):
    """Send N requests, report LB-acceptance PASS/FAIL, return metrics."""

    async def run(self):
        n = self.config.get("total_requests", 3)
        services = self.config.get("services", _SMOKE_SERVICES)

        self.logger.info(f"[smoke] starting — {n} request(s) to services {services}")
        self.metrics_collector.start_collection()

        requests = self.request_generator.generate_requests(
            count=n,
            service_selection="from_list",
            number_of_invocations=1,
            chained=False,
            input_data="None",
            run_multiple_invocations=False,
            service_list=services,
        )

        results = []
        async with LoadBalancerClient(base_url=self.load_balancer_url, timeout=15.0) as client:
            for i, payload in enumerate(requests):
                result = await self.send_request(client, payload)
                results.append(result)
                status = "OK" if result.get("success") else f"FAIL ({result.get('error', '?')})"
                self.logger.info(f"  [{i+1}/{n}] service={payload.get('service_id')}  {status}")
                if i < n - 1:
                    await asyncio.sleep(_SEND_INTERVAL_S)

        self.metrics_collector.stop_collection()

        accepted = sum(1 for r in results if r.get("success"))
        failed = n - accepted

        print("\n" + "=" * 60)
        if failed == 0:
            print(f"  SMOKE  PASS -- {accepted}/{n} requests accepted by LB")
        else:
            print(f"  SMOKE  FAIL -- {accepted}/{n} accepted, {failed} rejected by LB")
            for r in results:
                if not r.get("success"):
                    print(f"    service={r.get('service_id')}  error={r.get('error')}")
        print("=" * 60 + "\n")

        return self.metrics_collector

"""
Steady Load Scenario - Constant RPS over sustained periods with ramping.
"""
import asyncio
from pathlib import Path
from typing import Dict, Any, List

from scenarios.base_scenario import BaseScenario
from core.load_balancer_client import LoadBalancerClient

# testbed/ directory (parent of scenarios/)
_TESTBED_ROOT = Path(__file__).resolve().parent.parent


class SteadyLoadScenario(BaseScenario):
    """Steady load scenario for measuring throughput ceilings."""

    async def run(self) -> 'MetricsCollector':
        """Run the steady load scenario."""
        self.logger.info(f"Starting steady load scenario (run_id: {self.run_id})")
        self.metrics_collector.start_collection()

        rps_levels = self.config.get('rps_levels', [1, 5, 10, 20, 30, 50])
        duration_per_level = self.config.get('duration_per_level', 300)  # seconds
        services = self.config.get('services', [])
        interval = self.config.get('interval', 1.0)
        invocations = self.config.get('invocations', 1)

        total_requests = sum(int(rps * duration_per_level) for rps in rps_levels)

        self.logger.info(f"RPS levels: {rps_levels}, Duration per level: {duration_per_level}s")
        self.logger.info(f"Total requests across all levels: {total_requests}")

        level_request_lists: List[List[Dict[str, Any]]] = []

        if self.replay_file:
            saved_data = self.request_generator.load_requests(self.replay_file)
            all_saved = saved_data['requests']
            offset = 0
            for target_rps in rps_levels:
                n = int(target_rps * duration_per_level)
                chunk = all_saved[offset:offset + n]
                if len(chunk) < n:
                    self.logger.warning(
                        f"Replay file shorter than needed: wanted {n} requests for this level, "
                        f"got {len(chunk)} (offset {offset})"
                    )
                level_request_lists.append(chunk)
                offset += n
            self.logger.info(
                f"Replaying {sum(len(x) for x in level_request_lists)} requests from {self.replay_file}"
            )
        else:
            for target_rps in rps_levels:
                n = int(target_rps * duration_per_level)
                requests = self.request_generator.generate_requests(
                    count=n,
                    service_selection="from_list" if services else "weighted",
                    number_of_invocations=invocations,
                    chained=False,
                    input_data="None",
                    run_multiple_invocations=False,
                    service_list=services
                )
                level_request_lists.append(requests)

        if self.save_requests and not self.replay_file:
            flat = [r for lvl in level_request_lists for r in lvl]
            save_path = _TESTBED_ROOT / "results" / "requests" / f"{self.run_id}_requests.json"
            save_path.parent.mkdir(parents=True, exist_ok=True)
            self.request_generator.save_requests(flat, str(save_path))
            self.logger.info(f"Saved {len(flat)} requests to {save_path}")

        if self.save_only:
            self.logger.info("Save-only mode: Skipping request execution")
            self.metrics_collector.stop_collection()
            return self.metrics_collector

        async with LoadBalancerClient(base_url=self.load_balancer_url) as client:
            for level_idx, target_rps in enumerate(rps_levels):
                self.logger.info(
                    f"Starting RPS level {level_idx + 1}/{len(rps_levels)}: {target_rps} RPS"
                )

                request_interval = 1.0 / target_rps if target_rps > 0 else interval
                requests = level_request_lists[level_idx]
                total_for_level = len(requests)

                self.logger.info(
                    f"  Target: {target_rps} RPS, Interval: {request_interval:.3f}s, "
                    f"Total requests: {total_for_level}"
                )

                start_time = asyncio.get_event_loop().time()

                async def send_request_at_time(request_index: int, send_time: float):
                    await asyncio.sleep(max(0, send_time - asyncio.get_event_loop().time()))
                    payload = requests[request_index]
                    result = await self.send_request(client, payload)
                    return result

                tasks = []
                for i in range(total_for_level):
                    send_time = start_time + (i * request_interval)
                    task = asyncio.create_task(send_request_at_time(i, send_time))
                    tasks.append(task)

                results = await asyncio.gather(*tasks, return_exceptions=True)

                successful = sum(
                    1 for r in results
                    if not isinstance(r, Exception) and r.get('success', False)
                )
                self.logger.info(
                    f"  Level {level_idx + 1} completed: {successful}/{total_for_level} successful"
                )

        self.metrics_collector.stop_collection()

        await self.collect_batch_metrics()

        self.logger.info(f"Steady load scenario completed (run_id: {self.run_id})")

        return self.metrics_collector

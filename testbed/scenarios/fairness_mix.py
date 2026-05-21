"""
Fairness Mix Scenario - Three-phase shifting workload to evaluate per-service latency fairness.

RQ4: Across heterogeneous service mixes (light/medium/heavy), does ILP scheduling
produce more equitable per-service latency distributions than simpler policies?

Phases (defined in scenarios.yaml):
  1. light_dominant  - 200 req, services 13-17 only, 70% light weight
  2. balanced        - 200 req, all 13 services,    ~33% each category
  3. heavy_dominant  - 200 req, services 21-25 only, 70% heavy weight
"""
import asyncio
from typing import Dict, Any, List
from scenarios.base_scenario import BaseScenario
from core.load_balancer_client import LoadBalancerClient
from core.metrics_collector import MetricsCollector


class FairnessMixScenario(BaseScenario):
    """Three-phase heterogeneous workload scenario for scheduler fairness evaluation."""

    async def run(self) -> MetricsCollector:
        self.logger.info("Starting fairness_mix scenario (run_id: %s)", self.run_id)
        self.metrics_collector.start_collection()

        phases: List[Dict[str, Any]] = self.config.get('phases', [])
        frequency_config: Dict[str, Any] = self.config.get('frequency', {'type': 'uniform', 'min': 0.5, 'max': 3.0})
        invocations: int = self.config.get('invocations', 1)
        concurrency: int = self.config.get('concurrency', 10)
        ilp_config: Dict[str, Any] = self.config.get('ilp_config', {})

        seed = self.config.get('seed')
        if seed is not None:
            self.logger.info("Using random seed: %s (reproducible)", seed)

        if ilp_config:
            self.logger.info(
                "ILP Config: Expected batch size %s-%s, Max solve time: %ss",
                ilp_config.get('expected_batch_size_min', 'N/A'),
                ilp_config.get('expected_batch_size_max', 'N/A'),
                ilp_config.get('max_solve_time', 'N/A'),
            )

        if not phases:
            self.logger.error("No phases defined in fairness_mix config")  # noqa: logging-fstring-interpolation
            self.metrics_collector.stop_collection()
            return self.metrics_collector

        async with LoadBalancerClient(base_url=self.load_balancer_url) as client:
            semaphore = asyncio.Semaphore(concurrency)

            for phase_idx, phase in enumerate(phases):
                phase_name: str = phase.get('name', f'phase_{phase_idx}')
                request_count: int = phase.get('request_count', 200)
                phase_services: List[int] = phase.get('services', self.config.get('services', []))
                service_weights: Dict[str, float] = phase.get('service_weights', {})

                self.logger.info(
                    "Phase %d/%d: '%s' -- %d requests across %d services",
                    phase_idx + 1, len(phases), phase_name, request_count, len(phase_services)
                )

                # Generate requests for this phase
                requests = self.request_generator.generate_requests(
                    count=request_count,
                    service_selection="from_list",
                    number_of_invocations=invocations,
                    chained=False,
                    input_data="None",
                    run_multiple_invocations=False,
                    service_weights=service_weights,
                    service_list=phase_services
                )

                intervals = self.request_generator.generate_timing_sequence(
                    count=request_count,
                    **frequency_config
                )

                def make_task(index: int, reqs: list, ivls: list, pname: str):
                    async def _run():
                        async with semaphore:
                            if index > 0:
                                await asyncio.sleep(ivls[index - 1])
                            payload = reqs[index]
                            result = await self.send_request(client, payload)
                            if result.get('success'):
                                self.logger.debug(
                                    "[%s] Request %d/%d succeeded", pname, index + 1, len(reqs)
                                )
                            else:
                                self.logger.warning(
                                    "[%s] Request %d/%d failed: %s",
                                    pname, index + 1, len(reqs), result.get('error')
                                )
                    return _run()

                tasks = [make_task(i, requests, intervals, phase_name) for i in range(request_count)]
                completed = 0
                for coro in asyncio.as_completed(tasks):
                    await coro
                    completed += 1
                    if completed % 20 == 0:
                        self.logger.info(
                            "[%s] Progress: %d/%d requests completed",
                            phase_name, completed, request_count
                        )

                self.logger.info("Phase '%s' complete", phase_name)

        self.metrics_collector.stop_collection()
        await self.collect_batch_metrics()

        self.logger.info("fairness_mix scenario completed (run_id: %s)", self.run_id)
        return self.metrics_collector

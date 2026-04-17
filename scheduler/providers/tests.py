from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from developers.models import Services
from profiles.models import User
from providers.models import Job
from providers.prediction import PredictionInput, ServicePredInput
from providers.prediction.cpi_strategy import CPIStrategy
from providers.prediction.registry import reset_cache as reset_strategy_cache
from providers.prediction.scaling_strategy import ScalingFactorStrategy


class CPIStrategyUnitTests(TestCase):
    """Strategy-level unit tests. No DB / Django model writes."""

    def test_fully_populated_input_uses_compute_time(self):
        # 1e9 cycles * CPI 1.0 / 1 GHz = 1 second = 1000 ms.
        pi = PredictionInput(
            provider_id=1,
            cpi=Decimal("1.0"),
            memory_bandwidth=Decimal("10000000000"),
            clock_hz=1_000_000_000,
            services=[
                ServicePredInput(
                    service_id=42,
                    cpu_cycles_required=1_000_000_000,
                    memory_footprint=1_000,
                    memory_bytes_per_second=1_000,
                )
            ],
        )
        out = CPIStrategy().predict(pi)
        self.assertEqual(out.runtimes_ms[42], 1000)

    def test_memory_bound_service_picks_memory_time(self):
        # Memory: 10 GB / 1 GB/s = 10 s = 10_000 ms. Compute: trivial.
        pi = PredictionInput(
            provider_id=1,
            cpi=Decimal("1.0"),
            memory_bandwidth=Decimal("1000000000"),
            clock_hz=1_000_000_000,
            services=[
                ServicePredInput(
                    service_id=7,
                    cpu_cycles_required=1_000,
                    memory_footprint=10_000_000_000,
                )
            ],
        )
        out = CPIStrategy().predict(pi)
        self.assertEqual(out.runtimes_ms[7], 10_000)

    def test_missing_provider_fields_returns_none(self):
        pi = PredictionInput(
            provider_id=1,
            cpi=None,
            memory_bandwidth=None,
            clock_hz=None,
            services=[
                ServicePredInput(
                    service_id=1, cpu_cycles_required=1000, memory_footprint=1000
                )
            ],
        )
        self.assertIsNone(CPIStrategy().predict(pi).runtimes_ms[1])

    def test_missing_service_fields_returns_none(self):
        pi = PredictionInput(
            provider_id=1,
            cpi=Decimal("1.0"),
            memory_bandwidth=Decimal("1000000000"),
            clock_hz=1_000_000_000,
            services=[ServicePredInput(service_id=1)],
        )
        self.assertIsNone(CPIStrategy().predict(pi).runtimes_ms[1])

    def test_zero_clock_does_not_divide_by_zero(self):
        pi = PredictionInput(
            provider_id=1,
            cpi=Decimal("1.0"),
            memory_bandwidth=Decimal("1000000000"),
            clock_hz=0,
            services=[
                ServicePredInput(
                    service_id=1, cpu_cycles_required=1000, memory_footprint=None
                )
            ],
        )
        self.assertIsNone(CPIStrategy().predict(pi).runtimes_ms[1])


class GetPredictedRuntimesIntegrationTests(TestCase):
    """Exercise views.get_predicted_runtimes end-to-end against the CPI strategy.

    Asserts that MQTT is NOT called (get_mclient is patched to fail loudly) and
    that the DB-backed predict() path produces the expected number.
    """

    def setUp(self):
        reset_strategy_cache()
        self.developer = User.objects.create(is_developer=True)
        self.provider = User.objects.create(
            is_provider=True,
            ready=True,
            cpi=Decimal("1.0"),
            memory_bandwidth=Decimal("10000000000"),
            clock_hz=1_000_000_000,
        )
        self.service = Services.objects.create(
            developer=self.developer,
            name="svc",
            docker_container="test/img",
            active=True,
            cpu_cycles_required=1_000_000_000,
            memory_footprint=1_000,
        )

    def _mqtt_fail(self, *_a, **_kw):
        raise AssertionError("MQTT must not be used by the new prediction path")

    def test_predict_uses_db_not_mqtt(self):
        from providers import views

        with patch.object(views, "get_mclient", side_effect=self._mqtt_fail), patch.object(
            views, "_fetch_predicted_runtimes_mqtt_batch", side_effect=self._mqtt_fail
        ):
            result = views.get_predicted_runtimes(self.provider, [self.service])

        self.assertEqual(result[self.service.id], 1000)

    def test_job_fast_path_beats_predictor(self):
        from providers import views

        Job.objects.create(
            provider=self.provider,
            service=self.service,
            run_time=777,
            pull_time=0,
        )
        with patch.object(views, "_fetch_predicted_runtimes_mqtt_batch", side_effect=self._mqtt_fail):
            result = views.get_predicted_runtimes(self.provider, [self.service])
        self.assertEqual(result[self.service.id], 777)


class BuildCostMatrixIntegrationTests(TestCase):
    """Mixed case: one provider hits the Job fast path, the other hits predict()."""

    def setUp(self):
        reset_strategy_cache()
        self.developer = User.objects.create(is_developer=True)
        self.fast_provider = User.objects.create(is_provider=True, ready=True)
        self.predict_provider = User.objects.create(
            is_provider=True,
            ready=True,
            cpi=Decimal("1.0"),
            memory_bandwidth=Decimal("10000000000"),
            clock_hz=1_000_000_000,
        )
        self.service = Services.objects.create(
            developer=self.developer,
            name="svc",
            docker_container="test/img",
            active=True,
            cpu_cycles_required=1_000_000_000,
            memory_footprint=1_000,
        )
        Job.objects.create(
            provider=self.fast_provider,
            service=self.service,
            run_time=500,
            pull_time=0,
        )

    def test_cost_matrix_mixes_db_fastpath_and_predictor(self):
        from providers import views

        def _mqtt_fail(*_a, **_kw):
            raise AssertionError("MQTT must not be used by build_cost_matrix")

        with patch.object(views, "_fetch_predicted_runtimes_mqtt_batch", side_effect=_mqtt_fail):
            cm = views.build_cost_matrix(
                [self.fast_provider, self.predict_provider], [self.service]
            )

        fast_row = cm[self.fast_provider]
        pred_row = cm[self.predict_provider]
        self.assertEqual(list(fast_row.values())[0], 500)
        self.assertEqual(list(pred_row.values())[0], 1000)


class ScalingFactorStrategyUnitTests(TestCase):
    """Strategy-level unit tests for the scaling-factor predictor. No DB."""

    def _provider(self, **kwargs):
        defaults = dict(
            provider_id=1,
            r_cpu=1.0,
            r_mem=1.0,
            r_disk=1.0,
            r_net=1.0,
            s_disk_mbps=500.0,
            s_net_mbps=100.0,
        )
        defaults.update(kwargs)
        return PredictionInput(**defaults)

    def _service(self, service_id=1, **kwargs):
        defaults = dict(
            service_id=service_id,
            ref_runtime_ms=100.0,
            w_cpu=1.0,
            w_mem=0.0,
            w_disk=0.0,
            w_net=0.0,
            cache_state="memory",
        )
        defaults.update(kwargs)
        return ServicePredInput(**defaults)

    def test_pure_cpu_bound_cold_start(self):
        # w_cpu=1, r_cpu=2, t_ref=100 -> sigma=2 -> 200ms; memory cache -> +0.
        pi = self._provider(r_cpu=2.0)
        pi.services = [self._service()]
        out = ScalingFactorStrategy().predict(pi)
        self.assertEqual(out.runtimes_ms[1], 200)

    def test_equal_weights_cold_start(self):
        # Four equal weights over ratios (2, 1, 1, 1) -> sigma = 1.25 -> 62 ms.
        pi = self._provider(r_cpu=2.0, r_mem=1.0, r_disk=1.0, r_net=1.0)
        pi.services = [
            self._service(
                ref_runtime_ms=50.0,
                w_cpu=0.25,
                w_mem=0.25,
                w_disk=0.25,
                w_net=0.25,
            )
        ]
        out = ScalingFactorStrategy().predict(pi)
        # 50 * 1.25 = 62.5 -> round to 62 (banker's) or 63. Python round() uses
        # banker's rounding -> 62.
        self.assertEqual(out.runtimes_ms[1], round(62.5))

    def test_blend_half_and_half(self):
        # n=5, kappa=5 -> 50/50; ema=200, t_cold=100 -> 150.
        pi = self._provider()
        pi.services = [
            self._service(
                ref_runtime_ms=100.0,
                ema_runtime_ms=200.0,
                observation_count=5,
            )
        ]
        out = ScalingFactorStrategy().predict(pi)
        self.assertEqual(out.runtimes_ms[1], 150)

    def test_blend_history_dominates(self):
        # n=45, kappa=5 -> 90% EMA, 10% t_cold. ema=200, t_cold=100 -> 190.
        pi = self._provider()
        pi.services = [
            self._service(
                ref_runtime_ms=100.0,
                ema_runtime_ms=200.0,
                observation_count=45,
            )
        ]
        out = ScalingFactorStrategy().predict(pi)
        self.assertEqual(out.runtimes_ms[1], 190)

    def test_missing_weights_fall_back_to_equal(self):
        # No weights set at all -> equal 0.25 weights over ratios (2,1,1,1)
        # -> sigma = 1.25 -> 125ms.
        pi = self._provider(r_cpu=2.0)
        pi.services = [
            self._service(
                ref_runtime_ms=100.0,
                w_cpu=None,
                w_mem=None,
                w_disk=None,
                w_net=None,
            )
        ]
        out = ScalingFactorStrategy().predict(pi)
        self.assertEqual(out.runtimes_ms[1], 125)

    def test_missing_ratios_default_to_one(self):
        # Only r_cpu provided; others -> 1.0. Equal weights -> sigma = 1.25.
        pi = PredictionInput(provider_id=1, r_cpu=2.0)
        pi.services = [
            self._service(
                ref_runtime_ms=100.0,
                w_cpu=0.25,
                w_mem=0.25,
                w_disk=0.25,
                w_net=0.25,
            )
        ]
        out = ScalingFactorStrategy().predict(pi)
        self.assertEqual(out.runtimes_ms[1], 125)

    def test_partial_weights_renormalize(self):
        # w_cpu=0.5, w_mem=0.5 provided; disk/net missing -> zero-fill.
        # Renormalized: (0.5, 0.5, 0, 0). Ratios (2, 4, 99, 99) -> sigma=3
        # -> 100*3 = 300.
        pi = self._provider(r_cpu=2.0, r_mem=4.0, r_disk=99.0, r_net=99.0)
        pi.services = [
            self._service(
                ref_runtime_ms=100.0,
                w_cpu=0.5,
                w_mem=0.5,
                w_disk=None,
                w_net=None,
            )
        ]
        out = ScalingFactorStrategy().predict(pi)
        self.assertEqual(out.runtimes_ms[1], 300)

    def test_missing_t_ref_returns_none(self):
        pi = self._provider()
        pi.services = [self._service(ref_runtime_ms=None)]
        out = ScalingFactorStrategy().predict(pi)
        self.assertIsNone(out.runtimes_ms[1])

    def test_pull_time_memory_zero(self):
        # In-memory cache contributes 0 pull time regardless of image size.
        pi = self._provider()
        pi.services = [
            self._service(
                ref_runtime_ms=100.0,
                image_size_mb=1_000.0,
                cache_state="memory",
            )
        ]
        out = ScalingFactorStrategy().predict(pi)
        self.assertEqual(out.runtimes_ms[1], 100)

    def test_pull_time_disk_uses_s_disk(self):
        # V=500 MB / 500 MB/s = 1 s = 1000 ms. Plus t_cold=100 -> 1100.
        pi = self._provider(s_disk_mbps=500.0)
        pi.services = [
            self._service(
                ref_runtime_ms=100.0,
                image_size_mb=500.0,
                cache_state="disk",
            )
        ]
        out = ScalingFactorStrategy().predict(pi)
        self.assertEqual(out.runtimes_ms[1], 1100)

    def test_pull_time_cold_uses_s_net(self):
        # V=100 MB / 100 MB/s = 1 s = 1000 ms. Plus t_cold=100 -> 1100.
        pi = self._provider(s_net_mbps=100.0)
        pi.services = [
            self._service(
                ref_runtime_ms=100.0,
                image_size_mb=100.0,
                cache_state="cold",
            )
        ]
        out = ScalingFactorStrategy().predict(pi)
        self.assertEqual(out.runtimes_ms[1], 1100)

    def test_pull_time_missing_throughput_adds_zero(self):
        # Disk cache, image_size set, but s_disk_mbps missing -> pull time 0.
        pi = self._provider(s_disk_mbps=None)
        pi.services = [
            self._service(
                ref_runtime_ms=100.0,
                image_size_mb=500.0,
                cache_state="disk",
            )
        ]
        out = ScalingFactorStrategy().predict(pi)
        self.assertEqual(out.runtimes_ms[1], 100)

    def test_mixed_batch_partial_population(self):
        # Two services in one batch: one fully populated, one missing t_ref.
        pi = self._provider(r_cpu=2.0)
        pi.services = [
            self._service(service_id=10),
            self._service(service_id=20, ref_runtime_ms=None),
        ]
        out = ScalingFactorStrategy().predict(pi)
        self.assertEqual(out.runtimes_ms[10], 200)
        self.assertIsNone(out.runtimes_ms[20])

    def test_cache_state_none_treated_as_cold(self):
        # No cache_state provided -> "cold"; with no image_size, pull time 0.
        pi = self._provider()
        pi.services = [self._service(ref_runtime_ms=100.0, cache_state=None)]
        out = ScalingFactorStrategy().predict(pi)
        self.assertEqual(out.runtimes_ms[1], 100)

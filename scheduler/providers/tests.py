from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from developers.models import Services
from profiles.models import User
from providers.models import Job
from providers.prediction import PredictionInput, ServicePredInput
from providers.prediction.cpi_strategy import CPIStrategy
from providers.prediction.registry import reset_cache as reset_strategy_cache


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

import unittest
import json
from tempfile import TemporaryDirectory
from pathlib import Path

from aiops.config import load_runtime_config
from aiops.normalization import Normalizer, load_normalization_schema
from aiops.qualification import QualificationGate, load_qualification_schema
from aiops.schemas import Observation, SignalQuality


class QualificationGateTest(unittest.TestCase):
    def setUp(self):
        self.config = load_runtime_config(Path("config/runtime.json"))

    def qualify(self, observation: Observation, *, dev: bool = False):
        return QualificationGate(
            self.config,
            load_qualification_schema(Path("config/signal_qualification_schema.json")),
            dev=dev,
            max_sample_age_seconds=60,
        ).evaluate([observation])[0]

    def test_verifies_registered_signal_shape(self):
        result = self.qualify(
            Observation(
                signal_id="checkout_payment_error_rate_5m",
                value=0.2,
                unit="ratio",
                window="5m",
                quality=SignalQuality.UNQUALIFIED,
                labels={"service": "checkout", "dependency": "payment"},
            )
        )

        self.assertEqual(result.quality, SignalQuality.VERIFIED)

    def test_latency_normalizes_to_registered_seconds_unit(self):
        observation = Observation(
            signal_id="checkout_p95_latency_5m",
            value=250.0,
            unit="milliseconds",
            window="5m",
            quality=SignalQuality.UNQUALIFIED,
            labels={"service_name": "checkout"},
        )
        normalized = Normalizer(load_normalization_schema(Path("config/signal_normalization_schema.json"))).normalize([observation])[0]
        result = self.qualify(normalized)

        self.assertEqual(result.value, 0.25)
        self.assertEqual(result.unit, "seconds")
        self.assertEqual(result.quality, SignalQuality.VERIFIED)

    def test_marks_bad_signal_shapes_invalid(self):
        cases = [
            Observation(signal_id="checkout_payment_error_rate_5m", value=0.2, unit="ratio", window="5m", quality=SignalQuality.VERIFIED),
            Observation(signal_id="checkout_bad_ratio_24h", value=0.2, unit="count", window="24h", quality=SignalQuality.VERIFIED),
            Observation(signal_id="checkout_bad_ratio_24h", value=0.2, unit="ratio", window="5m", quality=SignalQuality.VERIFIED),
            Observation(signal_id="checkout_bad_ratio_24h", value=float("nan"), unit="ratio", window="24h", quality=SignalQuality.VERIFIED),
            Observation(signal_id="checkout_bad_ratio_24h", value=float("inf"), unit="ratio", window="24h", quality=SignalQuality.VERIFIED),
            Observation(signal_id="checkout_bad_ratio_24h", value=-0.1, unit="ratio", window="24h", quality=SignalQuality.VERIFIED),
            Observation(
                signal_id="checkout_bad_ratio_24h",
                value=0.2,
                unit="ratio",
                window="24h",
                quality=SignalQuality.VERIFIED,
                labels={"sample_timestamp": "bad"},
            ),
        ]

        self.assertEqual([self.qualify(case).quality for case in cases], [SignalQuality.INVALID] * len(cases))

    def test_rejects_mismatched_registry_metadata(self):
        cases = [
            Observation(
                signal_id="checkout_bad_ratio_24h",
                value=0.2,
                unit="ratio",
                window="24h",
                quality=SignalQuality.VERIFIED,
                labels={"query_id": "wrong.query"},
            ),
            Observation(
                signal_id="checkout_bad_ratio_24h",
                value=0.2,
                unit="ratio",
                window="24h",
                quality=SignalQuality.VERIFIED,
                labels={"service": "payment"},
            ),
            Observation(
                signal_id="checkout_bad_ratio_24h",
                value=0.2,
                unit="ratio",
                window="24h",
                quality=SignalQuality.VERIFIED,
                labels={"flow": "payment"},
            ),
        ]

        self.assertEqual([self.qualify(case).quality for case in cases], [SignalQuality.INVALID] * len(cases))

    def test_rejects_bad_series_shape(self):
        cases = [
            Observation(
                signal_id="checkout_bad_ratio_24h",
                value=0.2,
                unit="ratio",
                window="24h",
                quality=SignalQuality.VERIFIED,
                labels={"series_count": "2"},
            ),
            Observation(
                signal_id="checkout_bad_ratio_24h",
                value=0.2,
                unit="ratio",
                window="24h",
                quality=SignalQuality.VERIFIED,
                labels={"series_count": "bad"},
            ),
        ]

        self.assertEqual([self.qualify(case).quality for case in cases], [SignalQuality.INVALID] * len(cases))

    def test_marks_missing_unknown_and_stale_signals(self):
        cases = [
            Observation(signal_id="checkout_bad_ratio_24h", value=None, unit="ratio", window="24h", quality=SignalQuality.VERIFIED),
            Observation(signal_id="unknown_signal", value=1.0, unit="ratio", window="24h", quality=SignalQuality.VERIFIED),
            Observation(
                signal_id="checkout_bad_ratio_24h",
                value=0.2,
                unit="ratio",
                window="24h",
                quality=SignalQuality.VERIFIED,
                labels={"sample_timestamp": "0"},
            ),
        ]

        self.assertEqual(
            [self.qualify(case).quality for case in cases],
            [SignalQuality.MISSING, SignalQuality.UNQUALIFIED, SignalQuality.STALE],
        )

    def test_dev_mode_preserves_input_quality(self):
        result = self.qualify(
            Observation(
                signal_id="checkout_bad_ratio_24h",
                value=None,
                unit="count",
                window="5m",
                quality=SignalQuality.VERIFIED,
            ),
            dev=True,
        )

        self.assertEqual(result.quality, SignalQuality.VERIFIED)

    def test_fallback_only_is_not_promoted_to_verified(self):
        result = self.qualify(
            Observation(
                signal_id="checkout_bad_ratio_24h",
                value=0.2,
                unit="ratio",
                window="24h",
                quality=SignalQuality.FALLBACK_ONLY,
            )
        )

        self.assertEqual(result.quality, SignalQuality.FALLBACK_ONLY)

    def test_value_semantics_come_from_schema_file(self):
        with TemporaryDirectory() as directory:
            schema_path = Path(directory) / "schema.json"
            schema = json.loads(Path("config/signal_qualification_schema.json").read_text(encoding="utf-8"))
            schema["units"]["ratio"]["max"] = 0.1
            schema_path.write_text(json.dumps(schema), encoding="utf-8")

            result = QualificationGate(self.config, load_qualification_schema(schema_path)).evaluate(
                [
                    Observation(
                        signal_id="checkout_bad_ratio_24h",
                        value=0.2,
                        unit="ratio",
                        window="24h",
                        quality=SignalQuality.VERIFIED,
                    )
                ]
            )[0]

        self.assertEqual(result.quality, SignalQuality.INVALID)


if __name__ == "__main__":
    unittest.main()

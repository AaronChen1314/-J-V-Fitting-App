import unittest
from unittest.mock import patch

import numpy as np

import app


class CsvParsingTests(unittest.TestCase):
    def test_positive_current_is_normalized_and_rows_are_sorted(self):
        voltage, current = app.parse_jv_csv("V,J\n0.2,5\n0,10\n0.1,8\n")
        np.testing.assert_allclose(voltage, [0, 0.1, 0.2])
        np.testing.assert_allclose(current, [-10, -8, -5])

    def test_duplicate_voltage_values_are_averaged(self):
        voltage, current = app.parse_jv_csv("V,J\n0,10\n0.1,8\n0.1,6\n0.2,4\n")
        np.testing.assert_allclose(voltage, [0, 0.1, 0.2])
        np.testing.assert_allclose(current, [-10, -7, -4])

    def test_invalid_csv_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "至少需要"):
            app.parse_jv_csv("V,J\n0,not-a-number\n")


class ModelDiagnosticsTests(unittest.TestCase):
    def test_solver_failure_is_reported(self):
        failed_result = (np.array([-0.01]), {}, 5, "failed")
        with patch("app.fsolve", return_value=failed_result):
            _, diagnostics = app.double_diode_model(
                [0, 0.1, 0.2], 10, 1e-12, 1e-8, 1, 2, 1, 2000, return_diagnostics=True
            )
        self.assertEqual(diagnostics["failed_points"], 3)
        self.assertEqual(diagnostics["converged_points"], 0)

    def test_signed_log_residual_penalizes_wrong_sign(self):
        same_sign = np.abs(app.residual_values(np.array([-10.0]), np.array([-9.0]), True))[0]
        wrong_sign = np.abs(app.residual_values(np.array([-10.0]), np.array([9.0]), True))[0]
        self.assertGreater(wrong_sign, same_sign)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.app.config["TESTING"] = True
        cls.client = app.app.test_client()
        cls.samples = {
            name: path.read_text(encoding="utf-8-sig") for name, path in app.SAMPLE_FILES.items()
        }

    def test_preview_contract(self):
        response = self.client.post("/api/preview", json={"csv": self.samples["nbg"]})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["meta"]["solver"]["failed_points"], 0)
        self.assertEqual(len(data["V"]), len(data["J_fit"]))

    def test_invalid_bounds_return_clear_error(self):
        response = self.client.post(
            "/api/preview",
            json={"csv": self.samples["nbg"], "bounds": {"Rs": {"min": 10, "max": 1}}},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("最大值必须大于最小值", response.get_json()["error"])

    def test_all_parameters_locked(self):
        response = self.client.post(
            "/api/fit",
            json={"csv": self.samples["nbg"], "fixed": {name: True for name in app.PARAM_NAMES}},
        )
        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["meta"]["optimizer"]["message"], "全部参数已锁定。")

    def test_partial_parameter_lock(self):
        response = self.client.post(
            "/api/fit",
            json={
                "csv": self.samples["nbg"],
                "fixed": {"Jph": True, "n1": True, "n2": True, "Rs": True, "Rsh": True},
                "options": {"max_nfev": 40},
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["fixed"]["Jph"])

    def test_sample_regression_rmse(self):
        for sample_name, csv in self.samples.items():
            with self.subTest(sample=sample_name):
                response = self.client.post(
                    "/api/fit", json={"csv": csv, "options": {"max_nfev": 400}}
                )
                data = response.get_json()
                self.assertEqual(response.status_code, 200)
                self.assertLess(data["rmse"], 0.35)
                self.assertEqual(data["meta"]["solver"]["failed_points"], 0)


if __name__ == "__main__":
    unittest.main()

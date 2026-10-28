"""Static offline guards for the Open AP Wi-Fi startup state machine."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
STAGED = (ROOT / "main" / "staged.c").read_text(encoding="utf-8")
CAPTURE = (ROOT / "tools" / "capture_open_ap_poc.py").read_text(encoding="utf-8")


def c_function(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[brace:index + 1]
    raise AssertionError("unterminated C function: " + signature)


class OpenApInitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.setup = c_function(STAGED, "static bool configure_open_ap(void)")
        cls.mode = c_function(STAGED, "static void change_mode(unsigned mode)")

    def test_started_band_channel_and_csi_init_order(self):
        apis = [
            "esp_wifi_set_config", "esp_wifi_start", "esp_wifi_set_band_mode",
            "esp_wifi_set_channel", "esp_wifi_set_bandwidth",
            "esp_wifi_set_promiscuous(true)", "esp_wifi_set_csi_config",
            "esp_wifi_set_csi_rx_cb", "udp_receiver_task_start",
            "xTaskCreate(output_task)", "OPEN_AP_READY",
        ]
        positions = [self.setup.index(item) for item in apis]
        self.assertEqual(positions, sorted(positions))

    def test_csi_prerequisite_promiscuous_is_enabled_before_csi_config(self):
        self.assertLess(self.setup.index("esp_wifi_set_promiscuous(true)"),
                        self.setup.index("esp_wifi_set_csi_config"))
        self.assertIn("esp_wifi_set_promiscuous(true)", self.setup)

    def test_open_ap_setup_uses_api_level_errors_without_panic(self):
        self.assertNotIn("ESP_ERROR_CHECK", self.setup)
        self.assertNotIn("configASSERT", self.setup)
        self.assertIn("OPEN_AP_INIT_FAILED", STAGED)
        self.assertIn("esp_err_to_name(err)", STAGED)
        self.assertIn("open_ap_setup_failed=true", self.setup)

    def test_start_failure_prevents_later_started_only_apis(self):
        start = self.setup.index('OPEN_AP_TRY("esp_wifi_start"')
        band = self.setup.index('OPEN_AP_TRY("esp_wifi_set_band_mode"')
        self.assertLess(start, band)
        self.assertIn("if(failed_err!=ESP_OK)goto fail", self.setup)

    def test_ready_is_gated_on_channel_csi_and_udp_server(self):
        self.assertIn("if(!channel_readback_ok)", self.setup)
        self.assertIn("if(!atomic_load(&udp_server_ready))", self.setup)
        self.assertLess(self.setup.index('"xTaskCreate(output_task)"'),
                        self.setup.index('configured=true;open_ap_stats_control("OPEN_AP_READY")'))
        self.assertLess(self.setup.index('"udp_receiver_task_start"'),
                        self.setup.index('configured=true;open_ap_stats_control("OPEN_AP_READY")'))

    def test_csi_enable_failure_does_not_activate_udp_or_report_mode_ack(self):
        csi = self.mode.index('esp_wifi_set_csi(true)')
        failed = self.mode.index('if(csi_err!=ESP_OK)', csi)
        active = self.mode.index('atomic_store(&udp_server_active,true)', csi)
        ack = self.mode.index('control_event="MODE_ACK"', csi)
        self.assertLess(csi, failed)
        self.assertLess(failed, active)
        self.assertLess(active, ack)
        failure_block = self.mode[failed:active]
        self.assertIn("MODE_STOP", failure_block)
        self.assertIn("return", failure_block)

    def test_host_surfaces_init_failure_with_api_and_error(self):
        self.assertIn('"OPEN_AP_INIT_FAILED"', CAPTURE)
        self.assertIn('ready_event.get("api"', CAPTURE)
        self.assertIn('ready_event.get("err_name"', CAPTURE)


if __name__ == "__main__":
    unittest.main()

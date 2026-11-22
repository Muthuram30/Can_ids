"""Exercise Flask and IDS transitions with real python-can virtual buses.

No GPIO, Wi-Fi, USB payload, or network configuration is changed by these tests.
"""
import copy
import importlib.util
import json
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import patch

import can
import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from dotenv import dotenv_values

# A Pi runs this suite after creating its private .env. Keep its settings,
# hardware paths and credentials out of the controller fixtures and test output.
with patch.dict(os.environ), patch("dotenv.load_dotenv"):
    for key in dotenv_values(Path(__file__).resolve().parents[1] / ".env.example"):
        os.environ.pop(key, None)
    import app as gateway
from can_features import FEATURE_NAMES, extract_features
from scripts.setup_wifi import configure, settings
from scripts.install_usb import render

INITIAL_SECURITY = copy.deepcopy(gateway.security)
INITIAL_STATE = copy.deepcopy(gateway.state)


class GatewayTests(unittest.TestCase):
    def setUp(self):
        gateway.security.clear()
        gateway.security.update(copy.deepcopy(INITIAL_SECURITY))
        gateway.state.clear()
        gateway.state.update(copy.deepcopy(INITIAL_STATE))
        gateway.blocked_ips.clear()
        gateway.last_motor_cmd = None
        gateway.last_motor_source = None
        gateway.last_joystick_time = 0
        gateway.attacker_http_last = 0
        gateway.stop_event.clear()
        gateway.can_window.clear()
        gateway._mon.update(iface_state=None, present=None, absent_ticks=0,
                            absent_since=None, last_svc=0, last_status=0)
        self.tx = can.Bus(interface="virtual", channel=self.id())
        self.rx = can.Bus(interface="virtual", channel=self.id())
        gateway.bus = self.tx
        self.client = gateway.app.test_client()
        self.client.environ_base["REMOTE_ADDR"] = "192.0.2.5"

    def tearDown(self):
        self.tx.shutdown()
        self.rx.shutdown()
        gateway.bus = None

    def test_dashboard_renders_and_state_is_live_schema(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"joyBase", response.data)
        state = self.client.get("/api/state").get_json()
        self.assertEqual(state["security"]["phase"], "NORMAL")
        self.assertIn("motor", state["nodes"])

    def test_joystick_sends_real_can_frame(self):
        self.assertEqual(self.client.post("/api/joystick", json={"x": 0, "y": 90}).get_json(), {"cmd": "F"})
        message = self.rx.recv(0.2)
        self.assertEqual((message.arbitration_id, bytes(message.data)), (0x100, b"F"))

    def test_bad_joystick_requests_return_400(self):
        for body in (None, [], {"x": "bad"}, {"x": True}, {"y": False}, {"x": 101}, {"y": float("nan")}, {"x": float("inf")}):
            with self.subTest(body=body):
                self.assertEqual(self.client.post("/api/joystick", json=body).status_code, 400)
        self.assertIsNone(self.rx.recv(0.01))

    def test_solenoid_requires_an_explicit_json_boolean(self):
        for body in (None, [], {}, {"on": "false"}, {"on": 0}, {"on": 1}, {"on": None}):
            with self.subTest(body=body):
                self.assertEqual(self.client.post("/api/solenoid", json=body).status_code, 400)
        self.assertEqual(self.client.post("/api/solenoid", data="{bad", content_type="application/json").status_code, 400)
        self.assertIsNone(self.rx.recv(0.01))
        for on in (True, False):
            response = self.client.post("/api/solenoid", json={"on": on})
            self.assertEqual(response.status_code, 200)
            msg = self.rx.recv(0.2)
            self.assertEqual((msg.arbitration_id, bytes(msg.data)), (0x140, bytes([on])))

    def test_state_snapshot_has_no_nested_live_references(self):
        original_jsonify = gateway.jsonify

        def update_before_serialization(snapshot):
            gateway.state["nodes"]["motor"]["online"] = True
            gateway.security["ml"]["score"] = -10
            gateway.security["usb"]["status"] = "CHANGED"
            return original_jsonify(snapshot)

        with patch.object(gateway, "jsonify", side_effect=update_before_serialization):
            snapshot = self.client.get("/api/state").get_json()
        self.assertFalse(snapshot["nodes"]["motor"]["online"])
        self.assertIsNone(snapshot["security"]["ml"]["score"])
        self.assertEqual(snapshot["security"]["usb"]["status"], "IDLE")

    def test_request_already_validated_cannot_restart_motor_after_block(self):
        validated = threading.Event()
        result = []

        def request_in_thread():
            with gateway.app.test_client() as client:
                result.append(client.post("/api/joystick", json={"y": 100}).status_code)

        with gateway.motor_lock:
            with patch.object(gateway, "joystick_to_command", side_effect=lambda x,y: (validated.set() or "F")):
                worker = threading.Thread(target=request_in_thread, daemon=True)
                worker.start()
                self.assertTrue(validated.wait(2))
                gateway.security["detection_reason"] = "CAN_ANOMALY"
                gateway.last_motor_cmd = "F"
                gateway.execute_block(None)
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [403])
        self.assertEqual(bytes(self.rx.recv(0.2).data), b"S")
        self.assertIsNone(self.rx.recv(0.01))

    def test_blocked_client_cannot_cancel_containment_via_ml_toggle(self):
        self.client.environ_base["REMOTE_ADDR"] = gateway.ATTACKER_IP
        gateway.security["detection_reason"] = "NETWORK_ATTACKER_PRESENT"
        gateway.execute_block(gateway.ATTACKER_IP)
        gateway.security["ml"]["enabled"] = True
        self.assertEqual(self.client.post("/api/ml/toggle", json={"enabled": False}).status_code, 403)
        self.assertEqual(gateway.security["phase"], "BLOCKED")

    def test_mode_switch_during_scoring_discards_obsolete_result(self):
        gateway.security["ml"]["enabled"] = True
        inactive = dict(exists=False, up=False, has_ip=False, active=False)

        def score_while_switching():
            self.assertEqual(self.client.post("/api/ml/toggle", json={"enabled": False}).status_code, 200)
            self.assertEqual(self.client.post("/api/ml/toggle", json={"enabled": True}).status_code, 200)
            return -0.5, True

        # Ending on the same enabled value must still invalidate the old sample.
        with patch.object(gateway, "ml_bundle", object()), \
             patch.object(gateway, "ml_score_now", side_effect=score_while_switching), \
             patch.multiple(gateway, read_ap_interface=lambda: inactive,
                            service_active=lambda name: False,
                            read_usb_state=lambda now: dict(present=False, attack_triggered=False, status="IDLE", device=None)):
            gateway.monitor_tick(100)
        self.assertEqual(gateway.security["phase"], "NORMAL")
        self.assertIsNone(gateway.security["ml"]["score"])

    def test_can_shutdown_waits_for_send_and_closes_only_once(self):
        from unittest.mock import Mock
        started, release, closed = threading.Event(), threading.Event(), threading.Event()
        errors = []

        def send(*args, **kwargs):
            started.set()
            if not release.wait(2):
                errors.append("send was never released")
            if closed.is_set():
                errors.append("shutdown overlapped send")

        fake = Mock()
        fake.send.side_effect = send
        fake.shutdown.side_effect = closed.set
        gateway.bus = fake
        sending = threading.Thread(target=gateway.can_send, args=(can.Message(),), daemon=True)
        closing = threading.Thread(target=gateway.close_bus, daemon=True)
        try:
            sending.start()
            self.assertTrue(started.wait(2))
            closing.start()
            self.assertFalse(closed.wait(0.05))
        finally:
            release.set()
            sending.join(2)
            closing.join(2)
        self.assertFalse(sending.is_alive() or closing.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(closed.is_set())
        self.assertIsNone(gateway.bus)
        gateway.close_bus()
        fake.shutdown.assert_called_once()
        gateway.bus = self.tx
        gateway.close_bus(expected=fake)
        self.assertIs(gateway.bus, self.tx)

    def test_shutdown_prevents_reopening_bus(self):
        gateway.bus = None
        try:
            gateway.shutdown()
            with patch.object(can.interface, "Bus") as constructor:
                self.assertIsNone(gateway.get_bus())
                constructor.assert_not_called()
        finally:
            gateway.stop_event.clear()

    def test_synthetic_flood_scores_as_anomaly_through_live_path(self):
        from train_can_ids_model import simulate_normal, fit_model
        from can_features import WINDOW_SECONDS
        bundle = fit_model(simulate_normal(600, rng=random.Random(7)), 600)
        flood = [(100 + t * .002, 0x100, b"F") for t in range(1000)]
        with patch.object(gateway, "ml_bundle", bundle), patch.object(gateway.time, "time", return_value=102):
            gateway.can_window.extend(flood)
            score, anomaly = gateway.ml_score_now()
            self.assertLess(score, 0)
            self.assertTrue(anomaly)
            self.assertEqual(len(extract_features(flood)), len(FEATURE_NAMES))
            # Silent buses must not keep replaying stale attack windows forever.
            with patch.object(gateway.time, "time", return_value=102 + WINDOW_SECONDS + 1):
                gateway.ml_score_now()
            self.assertEqual(len(gateway.can_window), 0)

    def test_sensor_telemetry_updates_dashboard(self):
        gateway.handle_can_message(can.Message(arbitration_id=0x120, data=[0xE8, 3], is_extended_id=False))
        state = self.client.get("/api/state").get_json()
        self.assertEqual(state["tof_mm"], 1000)
        self.assertTrue(state["nodes"]["sensor"]["online"])

    def test_can_containment_stops_motor_and_denies_every_client(self):
        gateway.last_motor_cmd = "F"
        gateway.security["detection_reason"] = "CAN_ANOMALY"
        gateway.execute_block(None)
        self.assertEqual(bytes(self.rx.recv(0.2).data), b"S")
        for endpoint in ("/api/joystick", "/api/solenoid"):
            self.assertEqual(self.client.post(endpoint, json={}).status_code, 403)
        self.assertTrue(self.client.get("/api/state").get_json()["you"]["blocked"])
        self.assertEqual(self.client.get("/").status_code, 200)
        gateway.rearm("test condition cleared")
        self.assertEqual(self.client.post("/api/joystick", json={}).status_code, 200)

    def test_browser_timeout_stops_old_motor_command(self):
        gateway.last_motor_cmd = "F"
        gateway.last_joystick_time = time.time() - 5
        with patch.object(gateway.time, "sleep", side_effect=InterruptedError):
            with self.assertRaises(InterruptedError):
                gateway.motor_keepalive_loop()
        self.assertEqual(bytes(self.rx.recv(0.2).data), b"S")

    def test_held_joystick_does_not_time_out(self):
        gateway.last_motor_cmd = "F"
        gateway.last_joystick_time = time.time()
        gateway.last_motor_send_time = time.time() - 2
        with patch.object(gateway.time, "sleep", side_effect=InterruptedError):
            with self.assertRaises(InterruptedError):
                gateway.motor_keepalive_loop()
        self.assertEqual(bytes(self.rx.recv(0.2).data), b"F")

    def test_network_countdown_block_and_rearm(self):
        active = dict(exists=True, up=True, has_ip=True, active=True)
        with patch.multiple(gateway, read_ap_interface=lambda: active,
                            load_ml_model=lambda: None, service_active=lambda name: False,
                            read_usb_state=lambda now: dict(present=False, attack_triggered=False, status="IDLE", device=None)), \
             patch.object(gateway, "probe_attacker", return_value=(True, gateway.ATTACKER_IP)) as probe:
            gateway.monitor_tick(100)
            self.assertEqual(gateway.security["phase"], "COUNTDOWN")
            gateway.monitor_tick(100 + gateway.BLOCK_DELAY)
            self.assertEqual(gateway.security["phase"], "BLOCKED")
            self.client.environ_base["REMOTE_ADDR"] = gateway.ATTACKER_IP
            self.assertEqual(self.client.post("/api/joystick", json={}).status_code, 403)
            probe.return_value = (False, gateway.ATTACKER_IP)
            # Ignore the HTTP presence hint from the preceding test request.
            gateway.attacker_http_last = 0
            gateway.monitor_tick(200)
            gateway.monitor_tick(200 + gateway.REARM_COOLDOWN)
            self.assertEqual(gateway.security["phase"], "NORMAL")

    def test_missing_can_bus_does_not_prevent_dashboard(self):
        gateway.bus = None
        with patch.object(can.interface, "Bus", side_effect=can.CanError("no hardware")):
            self.assertIsNone(gateway.get_bus())
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_missing_model_is_reported_without_loading_thread(self):
        with patch.object(gateway, "ML_MODEL_PATH", "nonexistent-model.joblib"), \
             patch.object(gateway, "ml_bundle", None):
            gateway.load_ml_model()
            self.assertIsNone(gateway.ml_bundle)
            self.assertIn("could not load", gateway.ml_load_error)

    def test_usb_state_missing_malformed_and_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "usb.json"
            with patch.object(gateway, "USB_STATE_FILE", str(state_path)):
                self.assertFalse(gateway.read_usb_state(100)["present"])
                for data in ('{broken', '[]', '{"event_at":[]}'):
                    state_path.write_text(data)
                    self.assertFalse(gateway.read_usb_state(100)["present"])
                state_path.write_text(json.dumps(dict(present=True, attack_triggered=True,
                                                      status="MONITORING", event_at=10)))
                state = gateway.read_usb_state(100)
                self.assertEqual(state["status"], "REMOVED")
                self.assertFalse(state["present"])

    def test_usb_containment_remains_visible_after_payload_exits(self):
        gateway.security.update(phase="BLOCKED", detection_reason="USB_ATTACK")
        gateway.security["usb"].update(status="BLOCKED", event_id="insertion-1", payload_pid=123)
        inactive = dict(exists=False, up=False, has_ip=False, active=False)
        usb = dict(present=True, attack_triggered=True, status="MONITORING", device="1-1.3",
                   event_id="insertion-1", payload_pid=None)
        with patch.multiple(gateway, read_ap_interface=lambda: inactive, load_ml_model=lambda: None,
                            service_active=lambda name: False, read_usb_state=lambda now: dict(usb),
                            run=lambda *args, **kwargs: (0, "")):
            gateway.monitor_tick(100)
        self.assertEqual(gateway.security["usb"]["status"], "BLOCKED")

    def test_incompatible_model_does_not_disable_rule_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "offline.joblib"
            joblib.dump({"offline_model": "not the live bundle"}, model_path)
            with patch.object(gateway, "ML_MODEL_PATH", str(model_path)), \
                 patch.object(gateway, "ml_bundle", None):
                result = self.client.post("/api/ml/toggle", json={"enabled": True})
                self.assertEqual(result.status_code, 503)
                self.assertFalse(gateway.security["ml"]["enabled"])
                self.assertIsNone(gateway.ml_bundle)

    def test_real_model_roundtrip_and_live_scoring(self):
        with tempfile.TemporaryDirectory() as directory:
            features = np.array([extract_features([(j * .01, 0x011, bytes([i])) for j in range(i + 1)]) for i in range(30)])
            scaler = StandardScaler().fit(features)
            model = IsolationForest(n_estimators=10, random_state=7).fit(scaler.transform(features))
            model_path = Path(directory) / "live.joblib"
            joblib.dump(dict(scaler=scaler, model=model, feature_names=FEATURE_NAMES,
                             window_seconds=2.0), model_path)
            with patch.object(gateway, "ML_MODEL_PATH", str(model_path)), \
                 patch.object(gateway, "ml_bundle", None):
                self.assertEqual(self.client.post("/api/ml/toggle", json={"enabled": True}).status_code, 200)
                self.assertIsNone(gateway.ml_load_error)
                score, anomaly = gateway.ml_score_now()
                self.assertIsInstance(score, float)
                self.assertIsInstance(anomaly, bool)

    def test_incomplete_model_warns_once_and_recovers_after_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "live.joblib"
            path.touch()
            with patch.object(gateway, "ML_MODEL_PATH", str(path)), \
                 patch.object(gateway, "ml_bundle", None), patch.object(gateway, "ml_load_error", None):
                with self.assertLogs(gateway.log, "WARNING") as warned:
                    for _ in range(2):
                        self.assertEqual(self.client.post("/api/ml/toggle", json={"enabled": True}).status_code, 503)
                self.assertEqual(len(warned.records), 1)
                self.assertFalse(self.client.get("/api/state").get_json()["security"]["ml"]["enabled"])
                features = np.zeros((4, len(FEATURE_NAMES)))
                joblib.dump(dict(scaler=StandardScaler().fit(features),
                                 model=IsolationForest(n_estimators=2, random_state=7).fit(features),
                                 feature_names=FEATURE_NAMES, window_seconds=2.0), path)
                self.assertEqual(self.client.post("/api/ml/toggle", json={"enabled": True}).status_code, 200)
                self.assertIsNone(gateway.ml_load_error)

    def test_ml_toggle_requires_a_boolean(self):
        for body in ([], {"enabled": "false"}, {"enabled": 1}):
            self.assertEqual(self.client.post("/api/ml/toggle", json=body).status_code, 400)


class ConfigurationTests(unittest.TestCase):
    def test_model_save_creates_directory_and_preserves_previous_on_failure(self):
        from train_can_ids_model import save_model
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "new" / "model.joblib"
            save_model({"version": 1}, destination)
            self.assertEqual(joblib.load(destination), {"version": 1})
            before = destination.read_bytes()

            def interrupted_dump(bundle, temporary):
                Path(temporary).write_bytes(b"partial model")
                raise OSError("interrupted")

            with patch("train_can_ids_model.joblib.dump", side_effect=interrupted_dump):
                with self.assertRaises(OSError):
                    save_model({"version": 2}, destination)
            self.assertEqual(destination.read_bytes(), before)
            self.assertEqual(list(destination.parent.iterdir()), [destination])
            save_model({"version": 2}, destination)
            self.assertEqual(joblib.load(destination), {"version": 2})

    def test_controller_and_trainer_share_expanded_model_paths(self):
        import train_can_ids_model as trainer
        self.assertIs(trainer.project_path, gateway.project_path)
        for value, expected in (
            ("models/test.joblib", gateway.PROJECT_ROOT / "models/test.joblib"),
            (str(Path.home() / "absolute.joblib"), Path.home() / "absolute.joblib"),
            ("~/test.joblib", Path.home() / "test.joblib"),
        ):
            with self.subTest(value=value), patch.dict(os.environ, ML_MODEL_PATH=value):
                self.assertEqual(Path(trainer.project_path("ML_MODEL_PATH", "default.joblib")), expected)

    def test_offline_features_share_algorithm_but_keep_rate_overrides_separate(self):
        from ids import feature_extraction as offline
        from can_features import EXPECTED_RATE_HZ
        frames = [(0.5, 0x100, b"F"), (0.1, 0x120, b"\x12\x34"), (1.5, 0x999, b"X")]
        for window in ([], frames, [(0, 0x011, b"\x01")]):
            self.assertEqual(offline.extract_features(window), extract_features(window))
        original_rates = offline.EXPECTED_RATE_HZ.copy()
        try:
            offline.update_expected_rates({0x999: 1.0})
            self.assertEqual(offline.extract_features(frames)[2], 0)
            self.assertGreater(extract_features(frames)[2], 0)
            self.assertNotIn(0x999, EXPECTED_RATE_HZ)
        finally:
            offline.EXPECTED_RATE_HZ.clear()
            offline.EXPECTED_RATE_HZ.update(original_rates)
            offline.KNOWN_IDS.clear()
            offline.KNOWN_IDS.update(original_rates)

    def test_env_load_from_other_working_directory_and_environment_wins(self):
        # A private temporary project avoids touching the user's per-device .env.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("app.py", "can_features.py", "project_config.py"):
                (root / name).write_bytes((Path(gateway.__file__).parent / name).read_bytes())
            (root / ".env").write_text('APP_PORT=5088\nCAN_CHANNEL=virtual-test\nHOME_PASSWORD="space # secret"\nUSB_STATE_FILE=run/test.json\n')
            env = dict(os.environ, APP_PORT="5099")
            for key in ("CAN_CHANNEL", "HOME_PASSWORD", "USB_STATE_FILE"):
                env.pop(key, None)
            result = subprocess.run([sys.executable, "-c", "import importlib.util,sys,json,os; s=importlib.util.spec_from_file_location('isolated_gateway',sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(json.dumps([os.getenv('APP_PORT'),m.CAN_CHANNEL,os.getenv('HOME_PASSWORD') == 'space # secret',m.USB_STATE_FILE]))", str(root / "app.py")],
                                    cwd=root.parent, env=dict(env, PYTHONPATH=str(root) + os.pathsep + env.get("PYTHONPATH", "")),
                                    capture_output=True, text=True, check=True)
            port, channel, password_matches, state_path = json.loads(result.stdout.strip())
            self.assertEqual((port, channel, password_matches), ("5099", "virtual-test", True))
            self.assertEqual(Path(state_path), root / "run/test.json")

    def test_wifi_rejects_management_adapter_and_bad_password(self):
        good = dict(HOME_IFACE="wlan0", AP_IFACE="wlan1", AP_SSID="Lab AP", AP_PASSWORD="secret # 123", AP_IP="10.50.0.1")
        self.assertEqual(settings("ap", good), ("wlan1", "Lab AP", "secret # 123", "10.50.0.1"))
        for changes in ({"AP_IFACE": "wlan0"}, {"AP_PASSWORD": "short"}, {"AP_IP": "10.50.0.0"}):
            with self.assertRaises(ValueError):
                settings("ap", dict(good, **changes))

    def test_wifi_uses_exact_password_and_only_named_ap_profile(self):
        env = dict(AP_IFACE="wlan1", AP_SSID="Lab AP", AP_PASSWORD="space # secret")
        with patch("scripts.setup_wifi.run") as command, \
             patch("scripts.setup_wifi.subprocess.run") as status:
            status.return_value.returncode = 3
            command.return_value.stdout = ""
            configure("ap", env)
        calls = [call.args for call in command.call_args_list]
        self.assertTrue(any("space # secret" in args for args in calls))
        self.assertTrue(all("wlan0" not in args for args in calls))

    def test_usb_installer_requires_exact_serial_and_no_hardcoded_user(self):
        unit, rule = render(PurePosixPath("/home/test/Can_ids"), "test", "0781", "5581", "DEMO_123")
        self.assertIn("User=test", unit)
        self.assertIn("usb/usb_attack_trigger.py", unit)
        self.assertIn('ATTR{serial}=="DEMO_123"', rule)
        with self.assertRaises(ValueError):
            render(Path("/home/test/Can_ids"), "test", "0781", "5581", "")

    def test_usb_identity_fails_closed(self):
        spec = importlib.util.spec_from_file_location("usb_trigger", Path(gateway.__file__).parent / "usb/usb_attack_trigger.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.dict(os.environ, {"EXPECTED_VENDOR": "0781", "EXPECTED_PRODUCT": "5581", "EXPECTED_SERIAL": "DEMO"}):
            self.assertTrue(module.verify_identity(dict(vendor="0781", product="5581", serial="DEMO")))
            self.assertFalse(module.verify_identity(dict(vendor="0781", product="5581", serial="OTHER")))

    def test_eight_features_empty_and_unknown_frames(self):
        self.assertEqual(len(extract_features([])), 8)
        feats = extract_features([(0, 0x777, b"\x01"), (1, 0x777, b"\x02")])
        self.assertEqual(feats[FEATURE_NAMES.index("unknown_id_ratio")], 1)


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for feature-layer-to-cot.py

Run:  pytest tests/test_feature_layer_to_cot.py -v
Deps: pip install pytest requests-mock
"""

import json
import os
import sys
import tempfile
import pytest
import requests_mock as req_mock_module

# Allow importing the script directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..","python"))

from feature_layer_to_cot import (
    build_cot,
    load_config,
    DeltaTracker,
    FeatureLayerClient,
    DEFAULT_CONFIG,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

FM_DEFAULT = DEFAULT_CONFIG["field_mapping"]
COT_DEFAULT = DEFAULT_CONFIG["cot"]

SAMPLE_FEATURE = {
    "attributes": {
        "OBJECTID": 42,
        "name":     "Alpha Team",
        "EditDate": 1700000000000,
    },
    "geometry": {"x": -117.1611, "y": 32.7157}
}


# ── build_cot ─────────────────────────────────────────────────────────────────

class TestBuildCoT:

    def test_basic_output_is_valid_xml_fragment(self):
        cot = build_cot(SAMPLE_FEATURE, FM_DEFAULT, COT_DEFAULT)
        assert cot.startswith("<event ")
        assert cot.endswith("</event>")

    def test_uid_uses_objectid_by_default(self):
        cot = build_cot(SAMPLE_FEATURE, FM_DEFAULT, COT_DEFAULT)
        assert 'uid="EsriSync_42"' in cot

    def test_uid_prefix_is_configurable(self):
        fm = {**FM_DEFAULT, "uid_prefix": "MyOrg"}
        cot = build_cot(SAMPLE_FEATURE, fm, COT_DEFAULT)
        assert 'uid="MyOrg_42"' in cot

    def test_uid_field_is_configurable(self):
        fm = {**FM_DEFAULT, "uid_field": "name", "uid_prefix": "EsriSync"}
        cot = build_cot(SAMPLE_FEATURE, fm, COT_DEFAULT)
        assert 'uid="EsriSync_Alpha Team"' in cot

    def test_coordinates_from_geometry(self):
        cot = build_cot(SAMPLE_FEATURE, FM_DEFAULT, COT_DEFAULT)
        assert 'lat="32.7157"' in cot
        assert 'lon="-117.1611"' in cot

    def test_coordinates_from_explicit_fields(self):
        feature = {
            "attributes": {"OBJECTID": 1, "lat_field": 34.05, "lon_field": -118.24},
            "geometry": {}
        }
        fm = {**FM_DEFAULT, "lat": "lat_field", "lon": "lon_field"}
        cot = build_cot(feature, fm, COT_DEFAULT)
        assert 'lat="34.05"' in cot
        assert 'lon="-118.24"' in cot

    def test_default_cot_type(self):
        cot = build_cot(SAMPLE_FEATURE, FM_DEFAULT, COT_DEFAULT)
        assert 'type="a-f-G"' in cot

    def test_fixed_cot_type_override(self):
        fm = {**FM_DEFAULT, "cot_type": "a-h-G"}
        cot = build_cot(SAMPLE_FEATURE, fm, COT_DEFAULT)
        assert 'type="a-h-G"' in cot

    def test_cot_type_from_field(self):
        feature = {
            "attributes": {"OBJECTID": 1, "icon_type": "a-n-G"},
            "geometry": {"x": 0, "y": 0}
        }
        fm = {**FM_DEFAULT, "cot_type": "field:icon_type"}
        cot = build_cot(feature, fm, COT_DEFAULT)
        assert 'type="a-n-G"' in cot

    def test_cot_type_field_falls_back_when_missing(self):
        fm = {**FM_DEFAULT, "cot_type": "field:nonexistent_field"}
        cot = build_cot(SAMPLE_FEATURE, fm, COT_DEFAULT)
        assert 'type="a-f-G"' in cot

    def test_callsign_from_field(self):
        fm = {**FM_DEFAULT, "callsign_field": "name"}
        cot = build_cot(SAMPLE_FEATURE, fm, COT_DEFAULT)
        assert 'callsign="Alpha Team"' in cot

    def test_callsign_falls_back_to_uid_value(self):
        # callsign_field is empty → use uid value
        cot = build_cot(SAMPLE_FEATURE, FM_DEFAULT, COT_DEFAULT)
        assert 'callsign="42"' in cot

    def test_altitude_defaults_to_zero(self):
        cot = build_cot(SAMPLE_FEATURE, FM_DEFAULT, COT_DEFAULT)
        assert 'hae="0.0"' in cot

    def test_altitude_from_field(self):
        feature = {
            "attributes": {"OBJECTID": 1, "elev_m": 250.5},
            "geometry": {"x": 0, "y": 0}
        }
        fm = {**FM_DEFAULT, "altitude_field": "elev_m"}
        cot = build_cot(feature, fm, COT_DEFAULT)
        assert 'hae="250.5"' in cot

    def test_stale_time_is_configurable(self):
        from datetime import datetime, timezone, timedelta
        import xml.etree.ElementTree as ET

        cot_cfg = {**COT_DEFAULT, "stale_minutes": 15}
        cot = build_cot(SAMPLE_FEATURE, FM_DEFAULT, cot_cfg)
        root = ET.fromstring(cot)
        time_str  = root.attrib["time"].rstrip("Z")
        stale_str = root.attrib["stale"].rstrip("Z")
        t     = datetime.fromisoformat(time_str).replace(tzinfo=timezone.utc)
        stale = datetime.fromisoformat(stale_str).replace(tzinfo=timezone.utc)
        delta = stale - t
        assert abs(delta.total_seconds() - 900) < 2   # 15 min ± 2 s

    def test_remarks_fields_included(self):
        feature = {
            "attributes": {"OBJECTID": 1, "mission": "SAR-01", "sector": "North"},
            "geometry": {"x": 0, "y": 0}
        }
        fm = {**FM_DEFAULT, "remarks_fields": ["mission", "sector"]}
        cot = build_cot(feature, fm, COT_DEFAULT)
        assert "mission: SAR-01" in cot
        assert "sector: North" in cot

    def test_remarks_skips_empty_values(self):
        feature = {
            "attributes": {"OBJECTID": 1, "mission": "", "sector": None},
            "geometry": {"x": 0, "y": 0}
        }
        fm = {**FM_DEFAULT, "remarks_fields": ["mission", "sector"]}
        cot = build_cot(feature, fm, COT_DEFAULT)
        assert "<remarks></remarks>" in cot

    def test_null_geometry_does_not_crash(self):
        feature = {"attributes": {"OBJECTID": 1}, "geometry": {}}
        cot = build_cot(feature, FM_DEFAULT, COT_DEFAULT)
        assert 'lat="0.0"' in cot
        assert 'lon="0.0"' in cot


# ── DeltaTracker ──────────────────────────────────────────────────────────────

class TestDeltaTracker:

    def test_disabled_always_returns_true(self):
        dt = DeltaTracker(enabled=False, track_field="EditDate")
        assert dt.is_new_or_changed("uid_1", {"EditDate": 123}) is True
        assert dt.is_new_or_changed("uid_1", {"EditDate": 123}) is True  # same — still True

    def test_new_uid_returns_true(self):
        dt = DeltaTracker(enabled=True, track_field="EditDate")
        assert dt.is_new_or_changed("uid_1", {"EditDate": 1000}) is True

    def test_unchanged_uid_returns_false(self):
        dt = DeltaTracker(enabled=True, track_field="EditDate")
        dt.is_new_or_changed("uid_1", {"EditDate": 1000})
        assert dt.is_new_or_changed("uid_1", {"EditDate": 1000}) is False

    def test_changed_uid_returns_true(self):
        dt = DeltaTracker(enabled=True, track_field="EditDate")
        dt.is_new_or_changed("uid_1", {"EditDate": 1000})
        assert dt.is_new_or_changed("uid_1", {"EditDate": 2000}) is True

    def test_missing_track_field_always_returns_true(self):
        dt = DeltaTracker(enabled=True, track_field="EditDate")
        assert dt.is_new_or_changed("uid_1", {"SomeOtherField": 999}) is True
        # Second call with same data — still True because field is absent
        assert dt.is_new_or_changed("uid_1", {"SomeOtherField": 999}) is True

    def test_state_persists_across_instances(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            state_path = f.name

        try:
            DeltaTracker.STATE_PATH = state_path
            dt1 = DeltaTracker(enabled=True, track_field="EditDate")
            dt1.is_new_or_changed("uid_1", {"EditDate": 5000})
            dt1.commit()

            dt2 = DeltaTracker(enabled=True, track_field="EditDate")
            # Should see the saved state — not new
            assert dt2.is_new_or_changed("uid_1", {"EditDate": 5000}) is False
        finally:
            os.unlink(state_path)
            DeltaTracker.STATE_PATH = "/opt/Esri-TAKServer-Sync/delta-state.json"

    def test_multiple_uids_tracked_independently(self):
        dt = DeltaTracker(enabled=True, track_field="EditDate")
        dt.is_new_or_changed("uid_1", {"EditDate": 100})
        dt.is_new_or_changed("uid_2", {"EditDate": 200})

        assert dt.is_new_or_changed("uid_1", {"EditDate": 100}) is False
        assert dt.is_new_or_changed("uid_2", {"EditDate": 200}) is False
        assert dt.is_new_or_changed("uid_1", {"EditDate": 999}) is True
        assert dt.is_new_or_changed("uid_2", {"EditDate": 200}) is False


# ── Config loading ─────────────────────────────────────────────────────────────

class TestLoadConfig:

    def test_missing_file_returns_defaults(self):
        os.environ["ESRI_TAK_CONFIG"] = "/nonexistent/path/config.json"
        cfg = load_config()
        assert cfg["tak_server"]["port"] == 8089
        assert cfg["feature_layer"]["poll_interval"] == 30

    def test_partial_config_merges_with_defaults(self):
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            json.dump({"tak_server": {"port": 9000}}, f)
            path = f.name

        try:
            os.environ["ESRI_TAK_CONFIG"] = path
            cfg = load_config()
            assert cfg["tak_server"]["port"] == 9000          # overridden
            assert cfg["tak_server"]["host"] == "localhost"   # default preserved
            assert cfg["feature_layer"]["poll_interval"] == 30
        finally:
            os.unlink(path)

    def test_full_config_loads(self):
        full = {
            "tak_server":    {"host": "10.0.0.1", "port": 8089, "tls": True,
                              "cert_path": "/certs/test.p12", "cert_password": "secret", "ca_cert": ""},
            "feature_layer": {"url": "https://example.com/layer/0", "public": True,
                              "username": "", "password": "", "portal_url": "https://www.arcgis.com",
                              "poll_interval": 60, "page_size": 500},
            "field_mapping": {"lat": "", "lon": "", "uid_field": "OBJECTID",
                              "uid_prefix": "Test", "callsign_field": "name",
                              "cot_type": "a-f-G", "altitude_field": "",
                              "remarks_fields": ["notes"]},
            "cot":   {"stale_minutes": 10, "how": "m-g"},
            "delta": {"enabled": True, "track_field": "EditDate"}
        }
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            json.dump(full, f)
            path = f.name

        try:
            os.environ["ESRI_TAK_CONFIG"] = path
            cfg = load_config()
            assert cfg["feature_layer"]["url"] == "https://example.com/layer/0"
            assert cfg["field_mapping"]["callsign_field"] == "name"
            assert cfg["cot"]["stale_minutes"] == 10
        finally:
            os.unlink(path)


# ── FeatureLayerClient — token auth & 2FA ─────────────────────────────────────

class TestFeatureLayerClient2FA:

    BASE_CFG = {
        **DEFAULT_CONFIG,
        "feature_layer": {
            **DEFAULT_CONFIG["feature_layer"],
            "url":        "https://fake.arcgis.com/rest/services/Test/FeatureServer/0",
            "public":     False,
            "username":   "user",
            "password":   "pass",
            "portal_url": "https://fake.arcgis.com",
        }
    }

    def test_raises_on_2fa_message(self, requests_mock):
        requests_mock.post(
            "https://fake.arcgis.com/sharing/rest/generateToken",
            json={"error": {"code": 400, "message": "Multifactor authentication required"}}
        )
        with pytest.raises(RuntimeError, match="2FA"):
            FeatureLayerClient(self.BASE_CFG)

    def test_raises_on_generic_token_error(self, requests_mock):
        requests_mock.post(
            "https://fake.arcgis.com/sharing/rest/generateToken",
            json={"error": {"code": 403, "message": "Invalid credentials"}}
        )
        with pytest.raises(RuntimeError, match="ArcGIS token error 403"):
            FeatureLayerClient(self.BASE_CFG)

    def test_raises_when_token_missing_from_response(self, requests_mock):
        requests_mock.post(
            "https://fake.arcgis.com/sharing/rest/generateToken",
            json={"ssl": True}   # no "token" key
        )
        with pytest.raises(RuntimeError, match="missing 'token'"):
            FeatureLayerClient(self.BASE_CFG)

    def test_successful_token_obtained(self, requests_mock):
        requests_mock.post(
            "https://fake.arcgis.com/sharing/rest/generateToken",
            json={"token": "abc123", "expires": 60}
        )
        # Also stub the query so the client doesn't fail on init
        client = FeatureLayerClient(self.BASE_CFG)
        assert client._token == "abc123"


# ── FeatureLayerClient — pagination ──────────────────────────────────────────

class TestPagination:

    URL = "https://fake.arcgis.com/rest/services/Test/FeatureServer/0"
    CFG = {
        **DEFAULT_CONFIG,
        "feature_layer": {
            **DEFAULT_CONFIG["feature_layer"],
            "url":       URL,
            "public":    True,
            "page_size": 3,
        }
    }

    def _make_features(self, ids):
        return [{"attributes": {"OBJECTID": i}, "geometry": {"x": 0, "y": 0}} for i in ids]

    def test_single_page(self, requests_mock):
        requests_mock.get(
            f"{self.URL}/query",
            json={"features": self._make_features([1, 2])}
        )
        client = FeatureLayerClient(self.CFG)
        features = client.fetch_all()
        assert len(features) == 2

    def test_multiple_pages(self, requests_mock):
        # Page 1: full (3 records) → Page 2: partial (1 record) → stop
        def response(request, context):
            offset = int(request.qs.get("resultoffset", ["0"])[0])
            if offset == 0:
                return {"features": self._make_features([1, 2, 3])}
            return {"features": self._make_features([4])}

        requests_mock.get(f"{self.URL}/query", json=response)
        client = FeatureLayerClient(self.CFG)
        features = client.fetch_all()
        assert len(features) == 4
        assert [f["attributes"]["OBJECTID"] for f in features] == [1, 2, 3, 4]

    def test_exactly_page_size_then_empty(self, requests_mock):
        # First page returns exactly page_size → must fetch again; second is empty
        def response(request, context):
            offset = int(request.qs.get("resultoffset", ["0"])[0])
            if offset == 0:
                return {"features": self._make_features([1, 2, 3])}
            return {"features": []}

        requests_mock.get(f"{self.URL}/query", json=response)
        client = FeatureLayerClient(self.CFG)
        features = client.fetch_all()
        assert len(features) == 3

    def test_always_requests_wgs84(self, requests_mock):
        requests_mock.get(f"{self.URL}/query", json={"features": []})
        client = FeatureLayerClient(self.CFG)
        client.fetch_all()
        assert requests_mock.last_request.qs["outsr"] == ["4326"]

    def test_raises_on_layer_error_response(self, requests_mock):
        requests_mock.get(
            f"{self.URL}/query",
            json={"error": {"code": 400, "message": "Invalid layer"}}
        )
        client = FeatureLayerClient(self.CFG)
        with pytest.raises(RuntimeError, match="Feature Layer query error"):
            client.fetch_all()

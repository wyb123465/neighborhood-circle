import httpx
import pytest
from fastapi.testclient import TestClient

from backend.baidu import BaiduApiError, BaiduConfig, BaiduMapsClient
from backend.live_isochrone import _apply_row
from backend.main import app


@pytest.mark.parametrize('source,model', [('gcj02ll', '1'), ('wgs84ll', '2')])
def test_official_conversion_selects_source_and_longitude_first(source, model):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={'status': 0, 'result': [{'x': 121.435614, 'y': 31.225074}]})
    maps = BaiduMapsClient(BaiduConfig(ak='test', qps=1000), transport=httpx.MockTransport(handler))
    result = maps.convert_coordinates({'lat': 31.2, 'lng': 121.4}, source)
    assert seen[0].url.path == '/geoconv/v2/'
    assert seen[0].url.params['model'] == model
    assert seen[0].url.params['coords'] == '121.4,31.2'
    assert result['input_type'] == source and result['output_type'] == 'bd09ll'
    assert result['location'] == {'lng': 121.435614, 'lat': 31.225074}
    maps.close()


def test_bd09_is_identity_without_network_and_invalid_sources_stop():
    maps = BaiduMapsClient(BaiduConfig(ak=''), transport=httpx.MockTransport(lambda r: pytest.fail('no network expected')))
    position = {'lat': 31.2, 'lng': 121.4}
    assert maps.convert_coordinates(position)['location'] == position
    for source, location in [('guess', position), ('bd09ll', {'lat': float('nan'), 'lng': 121.4})]:
        with pytest.raises(BaiduApiError):
            maps.convert_coordinates(location, source)
    maps.close()


def test_invalid_conversion_response_is_not_used_as_center():
    maps = BaiduMapsClient(BaiduConfig(ak='test'), transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'status': 0, 'result': []})))
    with pytest.raises(BaiduApiError, match='未继续体检'):
        maps.convert_coordinates({'lat': 31.2, 'lng': 121.4}, 'wgs84ll')
    maps.close()


def test_unknown_coordinate_system_is_rejected_before_api_calls():
    client = TestClient(app)
    response = client.get('/api/live/isochrone', params={'lat': 31.2, 'lng': 121.4, 'coord_type': 'guess'})
    assert response.status_code == 422


def test_near_threshold_is_a_review_flag_without_changing_raw_verdict():
    point = {}
    _apply_row(point, {'duration_s': 852}, 900)
    assert point['status'] == 'reachable' and point['near_threshold']
    _apply_row(point, {'duration_s': 904}, 900)
    assert point['status'] == 'unreachable' and point['near_threshold']
    _apply_row(point, {'status': 'error'}, 900)
    assert point['status'] == 'unknown' and not point['near_threshold']

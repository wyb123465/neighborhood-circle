import httpx

from backend.baidu import BaiduConfig, BaiduMapsClient


def test_rate_reservations_do_not_expire_while_waiting_for_an_inflight_slot():
    clock, starts = [0.0], []

    def handler(request):
        starts.append(clock[0])
        return httpx.Response(200, json={"status": 0, "result": {"location": {"lat": 31.2, "lng": 121.4}}})

    class CongestedSlot:
        first = True

        def __enter__(self):
            if self.first:
                clock[0] += 10
                self.first = False

        def __exit__(self, *args):
            pass

    maps = BaiduMapsClient(
        BaiduConfig(ak="test", qps=2),
        transport=httpx.MockTransport(handler),
        clock=lambda: clock[0],
        sleep=lambda delay: clock.__setitem__(0, clock[0] + delay),
    )
    maps._limiter = CongestedSlot()
    maps.geocode("地址甲")
    maps.geocode("地址乙")
    maps.close()
    assert starts == [10.0, 10.5]

# developer: jbonilla
# Copyright © 2024 Taoshi Inc
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from tests.shared_objects.mock_classes import MockMetagraph
from tests.vali_tests.base_objects.test_base import TestBase
from time_util.time_util import TimeUtil, MS_IN_24_HOURS, MS_IN_8_HOURS
from vali_config import TradePair
from vali_objects.enums.order_type_enum import OrderType
from vali_objects.position import Position
from vali_objects.utils.live_price_fetcher import LivePriceFetcher
from vali_objects.utils.position_manager import PositionManager
from vali_objects.utils.vali_utils import ValiUtils
from vali_objects.vali_dataclasses.order import Order

class TestTimeUtil(TestBase):

    def setUp(self):
        super().setUp()
        secrets = ValiUtils.get_secrets()
        secrets["twelvedata_apikey"] = secrets["twelvedata_apikey"]
        self.live_price_fetcher = LivePriceFetcher(secrets=secrets, disable_ws=True)
        self.DEFAULT_MINER_HOTKEY = "test_miner"
        self.DEFAULT_POSITION_UUID = "test_position"
        self.DEFAULT_OPEN_MS = 1000
        self.DEFAULT_TRADE_PAIR = TradePair.BTCUSD
        self.default_position = Position(
            miner_hotkey=self.DEFAULT_MINER_HOTKEY,
            position_uuid=self.DEFAULT_POSITION_UUID,
            open_ms=self.DEFAULT_OPEN_MS,
            trade_pair=self.DEFAULT_TRADE_PAIR,
        )
        self.forex_position = Position(
            miner_hotkey=self.DEFAULT_MINER_HOTKEY,
            position_uuid=self.DEFAULT_POSITION_UUID,
            open_ms=self.DEFAULT_OPEN_MS,
            trade_pair=TradePair.EURUSD,
        )
        self.mock_metagraph = MockMetagraph([self.DEFAULT_MINER_HOTKEY])
        self.position_manager = PositionManager(metagraph=self.mock_metagraph, running_unit_tests=True)
        self.position_manager.init_cache_files()
        self.position_manager.clear_all_miner_positions_from_disk()

    def test_n_crypto_intervals(self):
        prev_delta = None
        for i in range(50):
            position = deepcopy(self.default_position)
            o1 = Order(order_type=OrderType.LONG,
                       leverage=1.0,
                       price=100,
                       trade_pair=TradePair.BTCUSD,
                       processed_ms=1719843814000,
                       order_uuid="1000")
            o2 = Order(order_type=OrderType.FLAT,
                       leverage=0.0,
                       price=110,
                       trade_pair=TradePair.BTCUSD,
                       processed_ms=1719843816000 + i * MS_IN_8_HOURS + i,
                       order_uuid="2000")


            position.orders = [o1, o2]
            position.rebuild_position_with_updated_orders()


            self.assertEqual(position.max_leverage_seen(), 1.0)
            self.assertEqual(position.get_cumulative_leverage(), 2.0)
            n_intervals, time_until_next_interval_ms = TimeUtil.n_intervals_elapsed_crypto(o1.processed_ms, o2.processed_ms)
            delta = time_until_next_interval_ms
            if i != 0:
                self.assertEqual(delta + 1, prev_delta, f"delta: {delta}, prev_delta: {prev_delta}")
            prev_delta = delta

            self.assertEqual(n_intervals, i, f"n_intervals: {n_intervals}, i: {i}")

    def test_n_forex_intervals(self):
        prev_delta = None
        for i in range(50):
            position = deepcopy(self.forex_position)
            o1 = Order(order_type=OrderType.LONG,
                         leverage=1.0,
                         price=1.1,
                         trade_pair=TradePair.EURUSD,
                         processed_ms=1719843814000,
                         order_uuid="1000")
            o2 = Order(order_type=OrderType.FLAT,
                            leverage=0.0,
                            price=1.2,
                            trade_pair=TradePair.EURUSD,
                            processed_ms=1719843816000 + i + MS_IN_24_HOURS * i,
                            order_uuid="2000")
            position.orders = [o1, o2]
            position.rebuild_position_with_updated_orders()
            self.assertEqual(position.max_leverage_seen(), 1.0)
            self.assertEqual(position.get_cumulative_leverage(), 2.0)
            n_intervals, time_until_next_interval_ms = TimeUtil.n_intervals_elapsed_forex_indices(o1.processed_ms,
                                                                                           o2.processed_ms)
            carry_fee, next_update_time_ms = position.crypto_carry_fee(o2.processed_ms)
            assert next_update_time_ms > o2.processed_ms, f"next_update_time_ms: {next_update_time_ms}, o2.processed_ms: {o2.processed_ms}"
            #self.assertGreater(time_until_next_interval_ms)
            delta = time_until_next_interval_ms
            if i != 0:
                self.assertEqual(delta + 1, prev_delta, f"delta: {delta}, prev_delta: {prev_delta}")
            prev_delta = delta

            self.assertEqual(n_intervals, i, f"n_intervals: {n_intervals}, i: {i}")


    def test_n_intervals_boundary(self):
        for i in range(1, 3):
            # Create a datetime object for 4 AM UTC today
            datetime_utc = datetime(2020, 7, 1, 4 + i*8, 0, 0, tzinfo=timezone.utc)
            t1 = int(datetime_utc.timestamp() * 1000) - 1
            t2 = int(datetime_utc.timestamp() * 1000)
            n_intervals, time_until_next_interval_ms = TimeUtil.n_intervals_elapsed_crypto(t1, t2)
            delta = time_until_next_interval_ms
            self.assertEqual(n_intervals, 1, f"n_intervals: {n_intervals}")
            self.assertEqual(delta, MS_IN_8_HOURS, f"delta: {delta}")

            t1 = int(datetime_utc.timestamp() * 1000)
            t2 = int(datetime_utc.timestamp() * 1000) + MS_IN_8_HOURS
            n_intervals, time_until_next_interval_ms = TimeUtil.n_intervals_elapsed_crypto(t1, t2)
            delta = time_until_next_interval_ms
            self.assertEqual(n_intervals, 1, f"n_intervals: {n_intervals}")
            self.assertEqual(delta, MS_IN_8_HOURS, f"delta: {delta}")


if __name__ == '__main__':
    import unittest
    unittest.main()
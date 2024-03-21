# developer: jbonilla
# Copyright © 2024 Taoshi Inc
import traceback
import time
from typing import List

from data_generator.twelvedata_service import TwelveDataService
from time_util.time_util import TimeUtil
from vali_config import ValiConfig, TradePair
from shared_objects.cache_controller import CacheController
from vali_objects.position import Position
from vali_objects.utils.position_manager import PositionManager
from vali_objects.utils.vali_utils import ValiUtils

import bittensor as bt

class MDDChecker(CacheController):
    MAX_DAILY_DRAWDOWN = 'MAX_DAILY_DRAWDOWN'
    MAX_TOTAL_DRAWDOWN = 'MAX_TOTAL_DRAWDOWN'
    def __init__(self, config, metagraph, position_manager, eliminations_lock, running_unit_tests=False):
        super().__init__(config, metagraph, running_unit_tests=running_unit_tests)
        secrets = ValiUtils.get_secrets()
        self.position_manager = position_manager
        assert self.running_unit_tests == self.position_manager.running_unit_tests
        self.all_trade_pairs = [trade_pair for trade_pair in TradePair]
        self.twelvedata = TwelveDataService(api_key=secrets["twelvedata_apikey"])
        self.eliminations_lock = eliminations_lock

    def get_required_closing_prices(self, hotkey_positions):
        required_trade_pairs = set()
        for sorted_positions in hotkey_positions.values():
            for position in sorted_positions:
                # Only need live price for open positions
                if position.is_closed_position:
                    continue
                required_trade_pairs.add(position.trade_pair)

        trade_pairs_list = list(required_trade_pairs)
        if len(trade_pairs_list) == 0:
            return {}
        return self.twelvedata.get_closes(trade_pairs=trade_pairs_list)
    
    def mdd_check(self):
        if not self.refresh_allowed(ValiConfig.MDD_CHECK_REFRESH_TIME_MS):
            time.sleep(1)
            return

        bt.logging.info("running mdd checker")
        self._refresh_eliminations_in_memory()

        hotkey_to_positions = self.position_manager.get_all_miner_positions_by_hotkey(
            self.metagraph.hotkeys, sort_positions=True,
            eliminations=self.eliminations
        )
        signal_closing_prices = self.get_required_closing_prices(hotkey_to_positions)
        any_eliminations = False
        for hotkey, sorted_positions in hotkey_to_positions.items():
            any_eliminations |= self._search_for_miner_dd_failures(hotkey, sorted_positions, signal_closing_prices)

        if any_eliminations:
            with self.eliminations_lock:
                self._write_eliminations_from_memory_to_disk()

        self.set_last_update_time()

    def _calculate_drawdown(self, final, initial):
        # Ex we went from return of 1 to 0.9. Drawdown is -10% or in this case -0.1. Return 1 - 0.1 = 0.9
        # Ex we went from return of 0.9 to 1. Drawdown is +10% or in this case 0.1. Return 1 + 0.1 = 1.1 (not really a drawdown)
        return 1.0 + ((float(final) - float(initial)) / float(initial))

    def _replay_all_closed_positions(self, hotkey: str, sorted_closed_positions: List[Position]) -> (bool, float):
        max_cuml_return_so_far = 1.0
        cuml_return = 1.0

        if len(sorted_closed_positions) == 0:
            bt.logging.info(f"no existing closed positions for [{hotkey}]")
            return False, cuml_return

        # Already sorted
        for position in sorted_closed_positions:
            position_return = position.return_at_close
            cuml_return *= position_return
            if cuml_return > max_cuml_return_so_far:
                max_cuml_return_so_far = cuml_return

            drawdown = self._calculate_drawdown(cuml_return, max_cuml_return_so_far)
            mdd_failure = self._is_drawdown_beyond_mdd(drawdown, time_now=TimeUtil.millis_to_datetime(position.close_ms))

            if mdd_failure:
                self.position_manager.close_open_positions_for_miner(hotkey)
                self.append_elimination_row(hotkey, drawdown, mdd_failure)
                return True, position_return

        # Replay of closed positions complete.
        return False, cuml_return


    def _search_for_miner_dd_failures(self, hotkey, sorted_positions, signal_closing_prices) -> bool:
        # Log sorted positions length
        if len(sorted_positions) == 0:
            return False
        # Already eliminated
        if self._hotkey_in_eliminations(hotkey):
            return False

        open_positions = []
        closed_positions = []
        for position in sorted_positions:
            if position.is_closed_position:
                closed_positions.append(position)
            else:
                open_positions.append(position)

        elimination_occurred, return_with_closed_positions = self._replay_all_closed_positions(hotkey, closed_positions)
        if elimination_occurred:
            return True

        open_position_trade_pairs = {
            position.position_uuid: position.trade_pair for position in open_positions
        }

        # Enforce only one open position per trade pair
        seen_trade_pairs = set()
        return_with_open_positions = return_with_closed_positions
        for open_position in open_positions:
            if open_position.trade_pair.trade_pair_id in seen_trade_pairs:
                raise ValueError(f"Miner [{hotkey}] has multiple open positions for trade pair [{open_position.trade_pair}]. Please restore cache.")
            else:
                seen_trade_pairs.add(open_position.trade_pair.trade_pair_id)
            realtime_price = signal_closing_prices[
                open_position_trade_pairs[open_position.position_uuid]
            ]
            open_position.set_returns(realtime_price, open_position.get_net_leverage())

            #bt.logging.success(f"current return with fees for [{open_position.position_uuid}] is [{open_position.return_at_close}]")
            return_with_open_positions *= open_position.return_at_close

        for position in closed_positions:
            seen_trade_pairs.add(position.trade_pair.trade_pair_id)
        # Log the dd for this miner and the positions trade_pairs they are in as well as total number of positions
        bt.logging.info(f"MDD checker -- current return for [{hotkey}] is [{return_with_open_positions}]. Seen trade pairs: {seen_trade_pairs}. n positions open [{len(open_positions)} / {len(sorted_positions)}]")

        dd_with_open_positions = self._calculate_drawdown(return_with_open_positions, return_with_closed_positions)
        mdd_failure = self._is_drawdown_beyond_mdd(dd_with_open_positions)
        if mdd_failure:
            self.position_manager.close_open_positions_for_miner(hotkey)
            self.append_elimination_row(hotkey, dd_with_open_positions, mdd_failure)

        return bool(mdd_failure)

    def _is_drawdown_beyond_mdd(self, dd, time_now=None) -> str | bool:
        if time_now is None:
            time_now = TimeUtil.generate_start_timestamp(0)
        if (dd < ValiConfig.MAX_DAILY_DRAWDOWN and time_now.hour == 0 and time_now.minute < 5):
            return MDDChecker.MAX_DAILY_DRAWDOWN
        elif (dd < ValiConfig.MAX_TOTAL_DRAWDOWN):
            return MDDChecker.MAX_TOTAL_DRAWDOWN
        else:
            return False







                


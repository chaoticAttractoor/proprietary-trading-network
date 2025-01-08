# developer: jbonilla
# Copyright © 2024 Taoshi Inc
import time
from typing import List, Dict

from time_util.time_util import TimeUtil
from vali_objects.enums.order_type_enum import OrderType
from vali_objects.vali_config import ValiConfig, TradePair
from shared_objects.cache_controller import CacheController
from vali_objects.position import Position
from vali_objects.utils.live_price_fetcher import LivePriceFetcher
from vali_objects.vali_dataclasses.order import Order, ORDER_SRC_ELIMINATION_FLAT
from vali_objects.vali_dataclasses.recent_event_tracker import RecentEventTracker

from vali_objects.utils.vali_utils import ValiUtils

import bittensor as bt

from vali_objects.vali_dataclasses.price_source import PriceSource


class MDDChecker(CacheController):

    def __init__(self, config, metagraph, position_manager, elimination_manager, running_unit_tests=False,
                 live_price_fetcher=None, shutdown_dict=None):
        super().__init__(config, metagraph, running_unit_tests=running_unit_tests)
        self.last_price_fetch_time_ms = None
        self.price_correction_enabled = True
        secrets = ValiUtils.get_secrets(running_unit_tests=running_unit_tests)
        self.position_manager = position_manager
        assert self.running_unit_tests == self.position_manager.running_unit_tests
        self.all_trade_pairs = [trade_pair for trade_pair in TradePair]
        if live_price_fetcher is None:
            self.live_price_fetcher = LivePriceFetcher(secrets=secrets)
        else:
            self.live_price_fetcher = live_price_fetcher
        self.elimination_manager = elimination_manager
        self.reset_debug_counters()
        self.shutdown_dict = shutdown_dict
        self.n_poly_api_requests = 0
        self.hotkeys_with_flat_orders_added = set()
        self.elimination_manager._refresh_eliminations_in_memory()
        self.eliminated_hotkeys = self.elimination_manager.get_eliminated_hotkeys()

    def reset_debug_counters(self):
        self.n_miners_skipped_already_eliminated = 0
        self.n_eliminations_this_round = 0
        self.n_orders_corrected = 0
        self.miners_corrected = set()


    def get_candle_data(self, hotkey_positions) -> Dict[TradePair, List[PriceSource]]:
        required_trade_pairs_for_candles = set()
        trade_pair_to_market_open = {}
        for sorted_positions in hotkey_positions.values():
            for position in sorted_positions:
                # Only need live price for open positions in open markets.
                if position.is_open_position:
                    tp = position.trade_pair
                    if tp not in trade_pair_to_market_open:
                        trade_pair_to_market_open[tp] = self.live_price_fetcher.polygon_data_service.is_market_open(tp)
                    if trade_pair_to_market_open[tp]:
                        required_trade_pairs_for_candles.add(tp)

        now = TimeUtil.now_in_millis()
        candle_data = self.live_price_fetcher.get_latest_prices(list(required_trade_pairs_for_candles))
        for tp, price_and_sources in candle_data.items():
            sources = price_and_sources[1]
            if sources and any(x and not x.websocket for x in sources):
                self.n_poly_api_requests += 1

        self.last_price_fetch_time_ms = now
        return candle_data

    
    def mdd_check(self):
        self.n_poly_api_requests = 0
        if not self.refresh_allowed(ValiConfig.MDD_CHECK_REFRESH_TIME_MS):
            time.sleep(1)
            return

        if self.shutdown_dict:
            return
        bt.logging.info("running mdd checker")
        self.reset_debug_counters()
        perf_ledger_eliminations = self.position_manager.perf_ledger_manager.pl_elimination_rows
        self.eliminated_hotkeys = self.elimination_manager.get_eliminated_hotkeys()
        for e in perf_ledger_eliminations:
            if e['hotkey'] in self.eliminated_hotkeys:
                continue

            self.eliminated_hotkeys.add(e['hotkey'])
            price_info = e['price_info']
            trade_pair_to_price_source_used_for_elimination_check = {}
            for k, v in price_info.items():
                trade_pair = TradePair.get_latest_tade_pair_from_trade_pair_str(k)
                elimination_initiated_time_ms = e['elimination_initiated_time_ms']
                trade_pair_to_price_source_used_for_elimination_check[trade_pair] = PriceSource(source='elim', open=v, close=v, start_ms=elimination_initiated_time_ms, timespan_ms=1000, websocket=False, trade_pair=trade_pair)
            self.position_manager.handle_eliminated_miner(e['hotkey'], trade_pair_to_price_source_used_for_elimination_check)
            self.elimination_manager.append_elimination_row(e)
            self.n_eliminations_this_round += 1

        if self.n_eliminations_this_round:
            with self.elimination_manager.eliminations_lock:
                self.elimination_manager.save_eliminations()
                bt.logging.info(f'Wrote {self.n_eliminations_this_round} new eliminations to disk')

        # Update in response to dereg'd miners re-registering an uneliminating
        self.hotkeys_with_flat_orders_added = {
            x for x in self.hotkeys_with_flat_orders_added if self.elimination_manager.hotkey_in_eliminations(x)
        }

        hotkey_to_positions = self.position_manager.get_all_miner_positions_by_hotkey(
            self.metagraph.hotkeys, sort_positions=True,
            eliminations=[{'hotkey': x} for x in self.hotkeys_with_flat_orders_added]
        )
        candle_data = self.get_candle_data(hotkey_to_positions)
        for hotkey, sorted_positions in hotkey_to_positions.items():
            if self.shutdown_dict:
                return
            self.perform_price_corrections(hotkey, sorted_positions, candle_data)

        bt.logging.info(f"mdd checker completed. n_eliminations_this_round: "
                        f"{self.n_eliminations_this_round}. "
                        f"n orders corrected: {self.n_orders_corrected}. n miners corrected: {len(self.miners_corrected)}."
                        f" n_poly_api_requests: {self.n_poly_api_requests}")
        self.set_last_update_time(skip_message=True)

    def _update_position_returns_and_persist_to_disk(self, hotkey, position, candle_data_dict) -> Position:
        """
        Setting the latest returns and persisting to disk for accurate MDD calculation and logging in get_positions

        Won't account for a position that was added in the time between mdd_check being called and this function
        being called. But that's ok as we will process such new positions the next round.
        """

        def _get_sources_for_order(order, trade_pair, is_last_order):
            # Only fall back to REST if the order is the latest. Don't want to get slowed down
            # By a flurry of recent orders.
            #ws_only = not is_last_order
            self.n_poly_api_requests += 1#0 if ws_only else 1
            sources = self.live_price_fetcher.fetch_prices([trade_pair],
                                                        {trade_pair: order.processed_ms},
                                                        ws_only=False).get(trade_pair, (None, None))[1]
            return sources

        trade_pair = position.trade_pair
        trade_pair_id = trade_pair.trade_pair_id
        orig_return = position.return_at_close
        orig_avg_price = position.average_entry_price
        orig_iep = position.initial_entry_price
        now_ms = TimeUtil.now_in_millis()
        with self.position_manager.position_locks.get_lock(hotkey, trade_pair_id):
            # Position could have updated in the time between mdd_check being called and this function being called
            position = self.position_manager.get_miner_position_from_disk_using_position_in_memory(position)
            n_orders_updated = 0
            for i, order in enumerate(reversed(position.orders)):
                if not self.price_correction_enabled:
                    break

                order_age = now_ms - order.processed_ms
                if order_age > RecentEventTracker.OLDEST_ALLOWED_RECORD_MS:
                    break  # No need to check older records

                sources = _get_sources_for_order(order, position.trade_pair, is_last_order=i == 0)
                if not sources:
                    bt.logging.warning(f"Unexpectedly could not find any new price sources for order"
                                     f" {order.order_uuid} in {hotkey} {position.trade_pair.trade_pair}. If this"
                                     f"issue persist, alert the team.")
                    continue
                if PriceSource.update_order_with_newest_price_sources(order, sources, hotkey, position.trade_pair.trade_pair):
                    n_orders_updated += 1

            # Rebuild the position with the newest price
            if n_orders_updated:
                position.rebuild_position_with_updated_orders()
                bt.logging.info(f"Retroactively updated {n_orders_updated} order prices for {position.miner_hotkey} {position.trade_pair.trade_pair}  "
                                    f"return_at_close changed from {orig_return:.8f} to {position.return_at_close:.8f} "
                                    f"avg_price changed from {orig_avg_price:.8f} to {position.average_entry_price:.8f} "
                                   f"initial_entry_price changed from {orig_iep:.8f} to {position.initial_entry_price:.8f}")

            # Log return before calling set_returns
            #bt.logging.info(f"current return with fees for open position with trade pair[{open_position.trade_pair.trade_pair_id}] is [{open_position.return_at_close}]. Position: {position}")
            temp = candle_data_dict.get(trade_pair, (None, None))
            realtime_price = temp[0]
            ret_changed = False
            if position.is_open_position and realtime_price is not None:
                orig_return = position.return_at_close
                position.set_returns(realtime_price)
                ret_changed = orig_return != position.return_at_close

            if n_orders_updated or ret_changed:
                is_liquidated = position.current_return == 0
                self.position_manager.save_miner_position(position, delete_open_position_if_exists=is_liquidated)
                self.n_orders_corrected += n_orders_updated
                self.miners_corrected.add(hotkey)

            #bt.logging.info(f"updated return with fees for open position with trade pair[{open_position.trade_pair.trade_pair_id}] is [{position.return_at_close}]. position: {position}")
            return position


    def add_manual_flat_orders(self, hotkey:str, sorted_positions:List[Position], corresponding_elimination):
        """
        Add flat orders to the positions for a miner that has been eliminated.
        """
        any_changes_attempted = False
        elimination_time_ms = corresponding_elimination['elimination_initiated_time_ms']

        # @@@@TEMP DEBUG@@@@@@
        #for position in sorted_positions:
        #    rewind = False
        #    for order in position.orders:
        #        if order.src == ORDER_SRC_ELIMINATION_FLAT:
        #            rewind = True
        #            break
        #    if rewind:
        #        position.orders = [o for o in position.orders if o.src != ORDER_SRC_ELIMINATION_FLAT]
        #        position.rebuild_position_with_updated_orders()
        #        assert position.is_open_position, position
        # @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
        for position in sorted_positions:
            with self.position_manager.position_locks.get_lock(hotkey, position.trade_pair.trade_pair_id):
                # Position could have updated in the time between mdd_check being called and this function being called
                position = self.position_manager.get_miner_position_from_disk_using_position_in_memory(position)
                if position.is_closed_position:
                    continue

                any_changes_attempted = True
                fake_flat_order_time = elimination_time_ms
                if position.orders and position.orders[-1].processed_ms > elimination_time_ms:
                    bt.logging.warning(f'Unexpectedly found a position with a processed_ms {position.orders[-1].processed_ms} greater than the elimination time {elimination_time_ms} ')
                    fake_flat_order_time = position.orders[-1].processed_ms + 1

                flat_order = Order(price=0,
                                   processed_ms=fake_flat_order_time,
                                   order_uuid=position.position_uuid[::-1],  # determinstic across validators. Won't mess with p2p sync
                                   trade_pair=position.trade_pair,
                                   order_type=OrderType.FLAT,
                                   leverage=0,
                                   src=ORDER_SRC_ELIMINATION_FLAT)
                position.add_order(flat_order)
                self.position_manager.save_miner_position(position, delete_open_position_if_exists=True)
                bt.logging.info(f'Added flat order for miner {hotkey} that has been eliminated. Trade pair: {position.trade_pair.trade_pair_id}. flat order: {flat_order}. position uuid {position.position_uuid}')

        if not any_changes_attempted:
            bt.logging.info(f'No flat order additions attempted for miner {hotkey} that has been eliminated. No open positions.')

    def perform_price_corrections(self, hotkey, sorted_positions, candle_data) -> bool:
        if len(sorted_positions) == 0:
            return False
        # Already eliminated?
        corresponding_elimination = self.elimination_manager.hotkey_in_eliminations(hotkey)
        if corresponding_elimination:
            if hotkey not in self.hotkeys_with_flat_orders_added:
                self.add_manual_flat_orders(hotkey, sorted_positions, corresponding_elimination)
                self.hotkeys_with_flat_orders_added.add(hotkey)
            self.n_miners_skipped_already_eliminated += 1
            return False

        for position in sorted_positions:
            if self.shutdown_dict:
                return False
            # Perform needed updates
            if position.is_open_position or position.newest_order_age_ms <= RecentEventTracker.OLDEST_ALLOWED_RECORD_MS:
                self._update_position_returns_and_persist_to_disk(hotkey, position, candle_data)








                


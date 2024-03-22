import json
import logging
from copy import deepcopy
from typing import Optional, List
from pydantic import BaseModel, root_validator
from vali_config import TradePair
from vali_objects.vali_dataclasses.order import Order
from vali_objects.enums.order_type_enum import OrderType

import bittensor as bt


class Position(BaseModel):
    """Represents a position in a trading system.

    As a miner, you need to send in signals to the validators, who will keep track
    of your closed and open positions based on your signals. Miners are judged based
    on a 30-day rolling window of return with time decay, so they must continuously perform.

    A signal contains the following information:
    - Trade Pair: The trade pair you want to trade (e.g., major indexes, forex, BTC, ETH).
    - Order Type: SHORT, LONG, or FLAT.
    - Leverage: The amount of leverage for the order type.

    On the validator's side, signals are converted into orders. The validator specifies
    the price at which they fulfilled a signal, which is then used for the order.
    Positions are composed of orders.

    Rules:
    - Please refer to README.md for the rules of the trading system.
    """

    miner_hotkey: str
    position_uuid: str
    open_ms: int
    trade_pair: TradePair
    orders: List[Order] = []
    current_return: float = 1.0
    close_ms: Optional[int] = None
    return_at_close: float = 1.0
    net_leverage: float = 0.0
    average_entry_price: float = 0.0
    initial_entry_price: float = 0.0
    position_type: Optional[OrderType] = None
    is_closed_position: bool = False

    @root_validator(pre=True)
    def add_trade_pair_to_orders(cls, values):
        trade_pair = values.get('trade_pair')
        orders = values.get('orders', [])
        if trade_pair and orders:
            # Add the position-level trade_pair to each order
            updated_orders = []
            for order in orders:
                order['trade_pair'] = trade_pair
                updated_orders.append(order)
            values['orders'] = updated_orders
        return values

    def _strip_trade_pair_from_orders(self, d):
        if 'orders' in d:
            for order in d['orders']:
                if 'trade_pair' in order:
                    del order['trade_pair']
        return d

    def to_dict(self):
        d = deepcopy(self.dict())
        return self._strip_trade_pair_from_orders(d)

    def __str__(self):
        return self.to_json_string()

    def to_json_string(self) -> str:
        # Using pydantic's json method with built-in validation
        json_str = self.json()
        # Unfortunately, we can't tell pydantic v1 to strip certain fields so we do that here
        json_loaded = json.loads(json_str)
        json_compressed = self._strip_trade_pair_from_orders(json_loaded)
        return json.dumps(json_compressed)

    @classmethod
    def from_dict(cls, position_dict):
        # Assuming 'orders' and 'trade_pair' need to be parsed from dict representations
        # Adjust as necessary based on the actual structure and types of Order and TradePair
        if 'orders' in position_dict:
            position_dict['orders'] = [Order.parse_obj(order) for order in position_dict['orders']]
        if 'trade_pair' in position_dict and isinstance(position_dict['trade_pair'], dict):
            # This line assumes TradePair can be initialized directly from a dict or has a similar parsing method
            position_dict['trade_pair'] = TradePair.from_trade_pair_id(position_dict['trade_pair']['trade_pair_id'])

        # Convert is_closed_position to bool if necessary
        # (assuming this conversion logic is no longer needed if input is properly formatted for Pydantic)

        return cls(**position_dict)

    @staticmethod
    def _position_log(message):
        bt.logging.info("Position Notification - " + message)

    def get_net_leverage(self):
        return self.net_leverage

    def log_position_status(self):
        bt.logging.debug(
            f"position details: "
            f"close_ms [{self.close_ms}] "
            f"initial entry price [{self.initial_entry_price}] "
            f"net leverage [{self.net_leverage}] "
            f"average entry price [{self.average_entry_price}] "
            f"return_at_close [{self.return_at_close}]"
        )
        order_info = [
            {
                "order type": order.order_type.value,
                "leverage": order.leverage,
                "price": order,
            }
            for order in self.orders
        ]
        bt.logging.debug(f"position order details: " f"close_ms [{order_info}] ")

    def add_order(self, order: Order):
        if self.is_closed_position:
            logging.warning(
                "Miner attempted to add order to a closed/liquidated position. Ignoring."
            )
            return
        if order.trade_pair != self.trade_pair:
            raise ValueError(
                f"Order trade pair [{order.trade_pair}] does not match position trade pair [{self.trade_pair}]"
            )

        if self._clamp_leverage(order):
            if order.leverage == 0:
                # This order's leverage got clamped to zero.
                # Skip it since we don't want to consider this a FLAT position and we don't want to allow bad actors
                # to send in a bunch of spam orders.
                logging.warning(
                    f"Miner attempted to add exceed max leverage for trade pair {self.trade_pair.trade_pair_id}. "
                    f"Clamping to max leverage {self.trade_pair.max_leverage}"
                )
                return
        self.orders.append(order)
        self._update_position()

    def calculate_unrealized_pnl(self, current_price):
        if self.initial_entry_price == 0 or self.average_entry_price is None:
            return 1

        bt.logging.info(
            f"trade_pair: {self.trade_pair.trade_pair_id} current price: {current_price},"
            f" average entry price: {self.average_entry_price}, net leverage: {self.net_leverage}, "
            f"initial entry price: {self.initial_entry_price}"
        )
        gain = (
            (current_price - self.average_entry_price)
            * self.net_leverage
            / self.initial_entry_price
        )
        # Check if liquidated
        if gain <= -1.0:
            return 0
        net_return = 1 + gain
        return net_return

    def _handle_liquidation(self, order):
        self._position_log("position liquidated")
        self.close_out_position(order.processed_ms)

    def set_returns(self, realtime_price, net_leverage):
        self.current_return = self.calculate_unrealized_pnl(realtime_price)
        self.return_at_close = self.current_return * (
            1 - self.trade_pair.fees * abs(net_leverage)
        )

    def update_position_state_for_new_order(self, order, delta_leverage):
        """
        Must be called after every order to maintain accurate internal state. The variable average_entry_price has
        a name that can be a little confusing. Although it claims to be the average price, it really isn't.
        For example, it can take a negative value. A more accurate name for this variable is the weighted average
        entry price.
        """
        realtime_price = order.price
        assert self.initial_entry_price > 0, self.initial_entry_price
        new_net_leverage = self.net_leverage + delta_leverage

        self.set_returns(realtime_price, new_net_leverage)

        if self.current_return < 0:
            raise ValueError(f"current return must be positive {self.current_return}")

        if self.current_return == 0:
            self._handle_liquidation(order)
            return
        self._position_log(f"closed position total w/o fees [{self.current_return}]")
        self._position_log(f"closed return with fees [{self.return_at_close}]")

        if self.position_type == OrderType.FLAT:
            self.net_leverage = 0.0
        else:
            self.average_entry_price = (
                self.average_entry_price * self.net_leverage
                + realtime_price * delta_leverage
            ) / new_net_leverage
            self.net_leverage = new_net_leverage

    def initialize_position_from_first_order(self, order):
        self.initial_entry_price = order.price
        if self.initial_entry_price <= 0:
            raise ValueError("Initial entry price must be > 0")
        # Initialize the position type. It will stay the same until the position is closed.
        if order.leverage > 0:
            self._position_log("setting new position type as LONG")
            self.position_type = OrderType.LONG
        elif order.leverage < 0:
            self._position_log("setting new position type as SHORT")
            self.position_type = OrderType.SHORT
        else:
            raise ValueError("leverage of 0 provided as initial order.")

    def close_out_position(self, close_ms):
        self.position_type = OrderType.FLAT
        self.is_closed_position = True
        self.close_ms = close_ms

    def _clamp_leverage(self, order):
        proposed_leverage = self.net_leverage + order.leverage
        if self.position_type == OrderType.LONG and proposed_leverage > self.trade_pair.max_leverage:
            order.leverage = self.trade_pair.max_leverage - self.net_leverage
            return True
        elif self.position_type == OrderType.SHORT and proposed_leverage < -self.trade_pair.max_leverage:
            order.leverage = -self.trade_pair.max_leverage - self.net_leverage
            return True

        return False

    def _update_position(self):
        self.net_leverage = 0.0
        bt.logging.info(f"Updating position with n orders: {len(self.orders)}")
        for order in self.orders:
            if self.position_type is None:
                self.initialize_position_from_first_order(order)

            # Check if the new order flattens the position, explicitly or implicitly
            if (
                (
                    self.position_type == OrderType.LONG
                    and self.net_leverage + order.leverage <= 0
                )
                or (
                    self.position_type == OrderType.SHORT
                    and self.net_leverage + order.leverage >= 0
                )
                or order.order_type == OrderType.FLAT
            ):
                #self._position_log(
                #    f"Flattening {self.position_type.value} position from order {order}"
                #)
                self.close_out_position(order.processed_ms)

            # Reflect the current order in the current position's return.
            adjusted_leverage = (
                0.0 if self.position_type == OrderType.FLAT else order.leverage
            )
            #bt.logging.info(
            #    f"Updating position state for new order {order} with adjusted leverage {adjusted_leverage}"
            #)
            self.update_position_state_for_new_order(order, adjusted_leverage)

            # If the position is already closed, we don't need to process any more orders. break in case there are more orders.
            if self.position_type == OrderType.FLAT:
                break

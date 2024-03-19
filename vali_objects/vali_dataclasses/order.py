# developer: Taoshidev
# Copyright © 2024 Taoshi Inc

from dataclasses import dataclass

from vali_config import TradePair
from vali_objects.enums.order_type_enum import OrderType
from vali_objects.vali_dataclasses.signal import Signal
from enum import Enum, auto

class Order(Signal):
    def __init__(self, order_type: OrderType, leverage: float, price: float, trade_pair: TradePair, processed_ms: int, order_uuid: str):
        if price < 0:
            raise ValueError(f"Price must be greater than 0. Leverage provided - [{price}]")

        if processed_ms < 0:
            raise ValueError(f"processed_ms must be greater than 0. Leverage provided - [{processed_ms}]")

        if not isinstance(order_type, OrderType):
            raise ValueError(f"Order type value received is not of type trade pair [{order_type}].")

        if order_type == OrderType.LONG and leverage < 0:
            raise ValueError("Leverage must be positive for LONG orders.")

        if not isinstance(trade_pair, TradePair):
            raise ValueError(f"Trade pair value received is not of type trade pair [{trade_pair}].")

        # super init
        super().__init__(trade_pair=trade_pair,
                         order_type=order_type,
                         leverage=-1.0 * abs(leverage) if order_type == OrderType.SHORT else float(leverage))
        self.price = price
        self.processed_ms = processed_ms
        self.order_uuid = order_uuid

    def __str__(self):
        return str({'trade_pair': str(self.trade_pair.trade_pair_id), 'order_type': str(self.order_type), 'leverage': self.leverage,
                'price': self.price, 'processed_ms': self.processed_ms, 'order_uuid': self.order_uuid})

    @staticmethod
    def from_dict(order_dict):
        return Order(
                OrderType.from_string(order_dict["order_type"]),
                order_dict["leverage"],
                order_dict["price"],
                TradePair.from_trade_pair_id(order_dict["trade_pair"]["trade_pair_id"]),
                order_dict["processed_ms"],
                order_dict["order_uuid"],
            )
class OrderStatus(Enum):
    OPEN = auto()
    CLOSED = auto()
    ALL = auto()  # Represents both or neither, depending on your logic

"""Unit tests for src.exchange.symbol_mapper.SymbolMapper.

SymbolMapper has no external dependencies — all tests use direct instantiation.
"""

from __future__ import annotations

import pytest

from src.exchange.symbol_mapper import SymbolMapper


@pytest.fixture
def mapper() -> SymbolMapper:
    """An empty SymbolMapper (no market data loaded)."""
    return SymbolMapper()


@pytest.fixture
def loaded_mapper() -> SymbolMapper:
    """A SymbolMapper pre-loaded with a small set of realistic market entries."""
    m = SymbolMapper()
    m.load_markets(
        {
            "BTC/USDT": {"base": "BTC", "quote": "USDT"},
            "ETH/USDT": {"base": "ETH", "quote": "USDT"},
            "BNB/USDT": {"base": "BNB", "quote": "USDT"},
            "SOL/BTC": {"base": "SOL", "quote": "BTC"},
            "LINK/ETH": {"base": "LINK", "quote": "ETH"},
            "AAVE/USDC": {"base": "AAVE", "quote": "USDC"},
        }
    )
    return m


class TestLoadMarkets:
    def test_load_builds_forward_mapping(self, loaded_mapper: SymbolMapper) -> None:
        assert loaded_mapper.to_ccxt("BTCUSDT") == "BTC/USDT"
        assert loaded_mapper.to_ccxt("ETHUSDT") == "ETH/USDT"

    def test_load_builds_reverse_mapping(self, loaded_mapper: SymbolMapper) -> None:
        assert loaded_mapper.from_ccxt("BTC/USDT") == "BTCUSDT"
        assert loaded_mapper.from_ccxt("ETH/USDT") == "ETHUSDT"

    def test_load_handles_non_usdt_quotes(self, loaded_mapper: SymbolMapper) -> None:
        assert loaded_mapper.to_ccxt("SOLBTC") == "SOL/BTC"
        assert loaded_mapper.to_ccxt("LINKETH") == "LINK/ETH"

    def test_load_handles_usdc_quote(self, loaded_mapper: SymbolMapper) -> None:
        assert loaded_mapper.to_ccxt("AAVEUSDC") == "AAVE/USDC"

    def test_load_clears_old_data_on_reload(self) -> None:
        m = SymbolMapper()
        m.load_markets({"BTC/USDT": {"base": "BTC", "quote": "USDT"}})
        assert m.to_ccxt("BTCUSDT") == "BTC/USDT"
        m.load_markets({"ETH/USDT": {"base": "ETH", "quote": "USDT"}})
        assert m.to_ccxt("ETHUSDT") == "ETH/USDT"
        assert "BTCUSDT" not in m._platform_to_ccxt

    def test_load_empty_markets(self) -> None:
        m = SymbolMapper()
        m.load_markets({})
        assert m._platform_to_ccxt == {}
        assert m._ccxt_to_platform == {}

    def test_load_market_symbols_are_uppercased(self) -> None:
        m = SymbolMapper()
        m.load_markets({"BTC/USDT": {"base": "btc", "quote": "usdt"}})
        assert "BTCUSDT" in m._platform_to_ccxt


class TestToCcxt:
    def test_cache_hit_returns_exact_symbol(self, loaded_mapper: SymbolMapper) -> None:
        assert loaded_mapper.to_ccxt("BNBUSDT") == "BNB/USDT"

    def test_cache_miss_falls_back_to_heuristic(self, mapper: SymbolMapper) -> None:
        assert mapper.to_ccxt("BTCUSDT") == "BTC/USDT"

    def test_heuristic_strips_usdt(self, mapper: SymbolMapper) -> None:
        assert mapper.to_ccxt("ETHUSDT") == "ETH/USDT"

    def test_heuristic_strips_busd(self, mapper: SymbolMapper) -> None:
        assert mapper.to_ccxt("BTCBUSD") == "BTC/BUSD"

    def test_heuristic_strips_usdc(self, mapper: SymbolMapper) -> None:
        assert mapper.to_ccxt("ETHUSDC") == "ETH/USDC"

    def test_heuristic_strips_btc_quote(self, mapper: SymbolMapper) -> None:
        assert mapper.to_ccxt("ETHBTC") == "ETH/BTC"

    def test_heuristic_strips_eth_quote(self, mapper: SymbolMapper) -> None:
        assert mapper.to_ccxt("LINKETH") == "LINK/ETH"

    def test_heuristic_strips_bnb_quote(self, mapper: SymbolMapper) -> None:
        assert mapper.to_ccxt("ADABNB") == "ADA/BNB"

    def test_heuristic_fallback_last_resort(self, mapper: SymbolMapper) -> None:
        result = mapper.to_ccxt("XYZABC")
        assert result == "XY/ZABC"

    def test_heuristic_short_symbol_returned_unchanged(self, mapper: SymbolMapper) -> None:
        assert mapper.to_ccxt("USDT") == "USDT"


class TestFromCcxt:
    def test_cache_hit_returns_platform_symbol(self, loaded_mapper: SymbolMapper) -> None:
        assert loaded_mapper.from_ccxt("BTC/USDT") == "BTCUSDT"
        assert loaded_mapper.from_ccxt("ETH/USDT") == "ETHUSDT"

    def test_cache_miss_removes_slash(self, mapper: SymbolMapper) -> None:
        assert mapper.from_ccxt("BTC/USDT") == "BTCUSDT"
        assert mapper.from_ccxt("eth/usdt") == "ETHUSDT"

    def test_cache_miss_removes_hyphen(self, mapper: SymbolMapper) -> None:
        assert mapper.from_ccxt("BTC-USDT") == "BTCUSDT"

    def test_unknown_symbol_in_loaded_mapper_falls_back(self, loaded_mapper: SymbolMapper) -> None:
        assert loaded_mapper.from_ccxt("DOGE/USDT") == "DOGEUSDT"


class TestHeuristicToCcxt:
    def test_usdt_pair(self) -> None:
        assert SymbolMapper._heuristic_to_ccxt("BTCUSDT") == "BTC/USDT"

    def test_busd_pair(self) -> None:
        assert SymbolMapper._heuristic_to_ccxt("ETHBUSD") == "ETH/BUSD"

    def test_usdc_pair(self) -> None:
        assert SymbolMapper._heuristic_to_ccxt("SOLUSDC") == "SOL/USDC"

    def test_tusd_pair(self) -> None:
        assert SymbolMapper._heuristic_to_ccxt("BNBTUSD") == "BNB/TUSD"

    def test_btc_quote_pair(self) -> None:
        assert SymbolMapper._heuristic_to_ccxt("ETHBTC") == "ETH/BTC"

    def test_lowercase_input_is_uppercased(self) -> None:
        assert SymbolMapper._heuristic_to_ccxt("btcusdt") == "BTC/USDT"

    def test_short_symbol_returned_unchanged(self) -> None:
        assert SymbolMapper._heuristic_to_ccxt("USDT") == "USDT"
        assert SymbolMapper._heuristic_to_ccxt("BTC") == "BTC"


class TestRoundTrip:
    def test_round_trip_with_loaded_markets(self, loaded_mapper: SymbolMapper) -> None:
        for sym in ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLBTC", "LINKETH"]:
            ccxt = loaded_mapper.to_ccxt(sym)
            back = loaded_mapper.from_ccxt(ccxt)
            assert back == sym, f"Round-trip failed for {sym}: got {back}"

    def test_round_trip_heuristic_common_pairs(self, mapper: SymbolMapper) -> None:
        for sym in ["BTCUSDT", "ETHUSDT", "ADAUSDT", "SOLUSDT"]:
            ccxt = mapper.to_ccxt(sym)
            back = mapper.from_ccxt(ccxt)
            assert back == sym

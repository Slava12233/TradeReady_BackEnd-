"""Unit tests for agent/conversation/router.py — IntentRouter and IntentType."""

from __future__ import annotations

from unittest.mock import MagicMock

from agent.conversation.router import (
    _SLASH_COMMANDS,
    IntentRouter,
    IntentType,
    _default_general_handler,
    _default_trade_handler,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_session():
    return MagicMock()


async def _custom_trade_handler(session, message, **kwargs):
    return f"custom trade: {message}"


async def _custom_portfolio_handler(session, message, **kwargs):
    return f"custom portfolio: {message}"


# ---------------------------------------------------------------------------
# Tests: IntentType enum
# ---------------------------------------------------------------------------


class TestIntentType:
    def test_all_values_are_strings(self):
        for member in IntentType:
            assert isinstance(member.value, str)

    def test_expected_members_exist(self):
        expected = {"trade", "analyze", "portfolio", "journal", "learn", "permissions", "status", "general"}
        actual = {m.value for m in IntentType}
        assert expected == actual

    def test_value_attribute_is_plain_string(self):
        assert IntentType.TRADE.value == "trade"
        assert IntentType.PORTFOLIO.value == "portfolio"


# ---------------------------------------------------------------------------
# Tests: IntentRouter construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_all_intents_have_default_handlers(self):
        router = IntentRouter()
        for intent in IntentType:
            handler = router._registry.get(intent)
            assert handler is not None, f"No handler for {intent}"

    def test_custom_handlers_override_defaults(self):
        router = IntentRouter(handlers={IntentType.TRADE: _custom_trade_handler})
        assert router._registry[IntentType.TRADE] is _custom_trade_handler

    def test_other_intents_keep_defaults_when_partial_override(self):
        router = IntentRouter(handlers={IntentType.TRADE: _custom_trade_handler})
        # PORTFOLIO should still have the default placeholder
        assert router._registry[IntentType.PORTFOLIO] is not _custom_trade_handler


# ---------------------------------------------------------------------------
# Tests: register()
# ---------------------------------------------------------------------------


class TestRegister:
    def test_register_replaces_handler(self):
        router = IntentRouter()
        router.register(IntentType.TRADE, _custom_trade_handler)
        assert router._registry[IntentType.TRADE] is _custom_trade_handler

    def test_register_second_call_replaces_again(self):
        router = IntentRouter()
        router.register(IntentType.TRADE, _custom_trade_handler)
        router.register(IntentType.TRADE, _custom_portfolio_handler)
        assert router._registry[IntentType.TRADE] is _custom_portfolio_handler

    def test_register_does_not_affect_other_intents(self):
        router = IntentRouter()
        original_portfolio = router._registry[IntentType.PORTFOLIO]
        router.register(IntentType.TRADE, _custom_trade_handler)
        assert router._registry[IntentType.PORTFOLIO] is original_portfolio


# ---------------------------------------------------------------------------
# Tests: classify() — slash commands
# ---------------------------------------------------------------------------


class TestClassifySlashCommands:
    def test_slash_trade(self):
        router = IntentRouter()
        assert router.classify("/trade buy 0.01 BTC") == IntentType.TRADE

    def test_slash_buy(self):
        router = IntentRouter()
        assert router.classify("/buy ETHUSDT") == IntentType.TRADE

    def test_slash_sell(self):
        router = IntentRouter()
        assert router.classify("/sell BTC") == IntentType.TRADE

    def test_slash_analyze(self):
        router = IntentRouter()
        assert router.classify("/analyze BTCUSDT") == IntentType.ANALYZE

    def test_slash_analyse_british_spelling(self):
        router = IntentRouter()
        assert router.classify("/analyse ETHUSDT") == IntentType.ANALYZE

    def test_slash_portfolio(self):
        router = IntentRouter()
        assert router.classify("/portfolio") == IntentType.PORTFOLIO

    def test_slash_balance(self):
        router = IntentRouter()
        assert router.classify("/balance") == IntentType.PORTFOLIO

    def test_slash_positions(self):
        router = IntentRouter()
        assert router.classify("/positions") == IntentType.PORTFOLIO

    def test_slash_pnl(self):
        router = IntentRouter()
        assert router.classify("/pnl") == IntentType.PORTFOLIO

    def test_slash_journal(self):
        router = IntentRouter()
        assert router.classify("/journal bought BTC today") == IntentType.JOURNAL

    def test_slash_learn(self):
        router = IntentRouter()
        assert router.classify("/learn what is RSI") == IntentType.LEARN

    def test_slash_help(self):
        router = IntentRouter()
        assert router.classify("/help") == IntentType.LEARN

    def test_slash_permissions(self):
        router = IntentRouter()
        assert router.classify("/permissions") == IntentType.PERMISSIONS

    def test_slash_status(self):
        router = IntentRouter()
        assert router.classify("/status") == IntentType.STATUS

    def test_slash_health(self):
        router = IntentRouter()
        assert router.classify("/health") == IntentType.STATUS

    def test_slash_ping(self):
        router = IntentRouter()
        assert router.classify("/ping") == IntentType.STATUS

    def test_unknown_slash_command_falls_through_to_nlp(self):
        router = IntentRouter()
        # /foobar is not a registered slash command
        # After stripping the slash token, the remaining text is classified by NLP
        result = router.classify("/foobar")
        # Should not raise; should return a valid IntentType
        assert isinstance(result, IntentType)

    def test_slash_case_insensitive(self):
        router = IntentRouter()
        assert router.classify("/TRADE buy BTC") == IntentType.TRADE


# ---------------------------------------------------------------------------
# Tests: classify() — regex / NLP patterns
# ---------------------------------------------------------------------------


class TestClassifyNLP:
    def test_buy_keyword_maps_to_trade(self):
        router = IntentRouter()
        assert router.classify("I want to buy 0.1 ETH now") == IntentType.TRADE

    def test_sell_keyword_maps_to_trade(self):
        router = IntentRouter()
        assert router.classify("sell all my BTC") == IntentType.TRADE

    def test_go_long_maps_to_trade(self):
        router = IntentRouter()
        assert router.classify("I want to go long on SOLUSDT") == IntentType.TRADE

    def test_close_position_maps_to_trade(self):
        router = IntentRouter()
        assert router.classify("close my position on ETH") == IntentType.TRADE

    def test_analyze_keyword_maps_to_analyze(self):
        router = IntentRouter()
        assert router.classify("analyze the BTC chart") == IntentType.ANALYZE

    def test_rsi_maps_to_analyze(self):
        router = IntentRouter()
        assert router.classify("show me the RSI for ETH") == IntentType.ANALYZE

    def test_macd_maps_to_analyze(self):
        router = IntentRouter()
        assert router.classify("check the MACD signal") == IntentType.ANALYZE

    def test_portfolio_keyword_maps_to_portfolio(self):
        router = IntentRouter()
        assert router.classify("show me my portfolio") == IntentType.PORTFOLIO

    def test_balance_phrase_maps_to_portfolio(self):
        router = IntentRouter()
        # Avoid "what is" which triggers LEARN first; use phrasing that hits PORTFOLIO regex directly
        assert router.classify("show me my current balance") == IntentType.PORTFOLIO

    def test_pnl_phrase_maps_to_portfolio(self):
        router = IntentRouter()
        # P&L regex matches "\bp(?:&|and|/)l\b"
        assert router.classify("my P&L is negative today") == IntentType.PORTFOLIO

    def test_journal_verb_maps_to_journal(self):
        router = IntentRouter()
        assert router.classify("journal: bought BTC at 50000") == IntentType.JOURNAL

    def test_remind_me_maps_to_journal(self):
        router = IntentRouter()
        assert router.classify("remind me that I opened a long at 64k") == IntentType.JOURNAL

    def test_what_is_maps_to_learn(self):
        router = IntentRouter()
        assert router.classify("what is a Sharpe ratio?") == IntentType.LEARN

    def test_how_does_maps_to_learn(self):
        router = IntentRouter()
        assert router.classify("how does RSI work?") == IntentType.LEARN

    def test_explain_maps_to_learn(self):
        router = IntentRouter()
        assert router.classify("explain what a bollinger band is") == IntentType.LEARN

    def test_permissions_keyword_maps_to_permissions(self):
        router = IntentRouter()
        # Avoid "what are" which triggers LEARN; use a phrasing that hits PERMISSIONS regex directly
        assert router.classify("show my current permissions") == IntentType.PERMISSIONS

    def test_max_exposure_maps_to_permissions(self):
        router = IntentRouter()
        # "maximum trade limit" triggers the PERMISSIONS regex without triggering LEARN
        assert router.classify("check maximum trade limit settings") == IntentType.PERMISSIONS

    def test_status_keyword_maps_to_status(self):
        router = IntentRouter()
        assert router.classify("what is the platform status?") == IntentType.STATUS

    def test_online_maps_to_status(self):
        router = IntentRouter()
        assert router.classify("is the server online?") == IntentType.STATUS

    def test_ping_maps_to_status(self):
        router = IntentRouter()
        assert router.classify("ping") == IntentType.STATUS

    def test_empty_message_returns_general(self):
        router = IntentRouter()
        assert router.classify("") == IntentType.GENERAL

    def test_whitespace_only_returns_general(self):
        router = IntentRouter()
        assert router.classify("   ") == IntentType.GENERAL

    def test_unrecognised_message_returns_general(self):
        router = IntentRouter()
        result = router.classify("xyzzy quux florp")
        assert result == IntentType.GENERAL


# ---------------------------------------------------------------------------
# Tests: get_handler()
# ---------------------------------------------------------------------------


class TestGetHandler:
    def test_get_handler_returns_registered_handler(self):
        router = IntentRouter()
        router.register(IntentType.TRADE, _custom_trade_handler)
        handler = router.get_handler(IntentType.TRADE)
        assert handler is _custom_trade_handler

    def test_get_handler_falls_back_to_general_for_missing_intent(self):
        router = IntentRouter()
        # Manually remove an intent from registry to simulate missing handler
        del router._registry[IntentType.ANALYZE]
        handler = router.get_handler(IntentType.ANALYZE)
        # Should return the GENERAL handler
        assert handler is router._registry[IntentType.GENERAL]


# ---------------------------------------------------------------------------
# Tests: route()
# ---------------------------------------------------------------------------


class TestRoute:
    def test_route_returns_tuple(self):
        router = IntentRouter()
        result = router.route("buy BTC")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_route_intent_matches_classify(self):
        router = IntentRouter()
        intent, _ = router.route("buy BTC")
        assert intent == router.classify("buy BTC")

    def test_route_handler_is_callable(self):
        router = IntentRouter()
        _, handler = router.route("analyze ETH")
        assert callable(handler)

    async def test_route_handler_is_awaitable(self):
        router = IntentRouter()
        intent, handler = router.route("show my portfolio balance")
        session = _make_mock_session()
        result = await handler(session, "show my portfolio balance")
        assert isinstance(result, str)

    def test_route_custom_handler_returned(self):
        router = IntentRouter()
        router.register(IntentType.PORTFOLIO, _custom_portfolio_handler)
        intent, handler = router.route("show me my portfolio")
        assert intent == IntentType.PORTFOLIO
        assert handler is _custom_portfolio_handler


# ---------------------------------------------------------------------------
# Tests: default handler stubs
# ---------------------------------------------------------------------------


class TestDefaultHandlers:
    async def test_default_trade_handler_returns_string(self):
        session = _make_mock_session()
        result = await _default_trade_handler(session, "buy BTC")
        assert isinstance(result, str)
        assert "buy BTC" in result

    async def test_default_general_handler_returns_string(self):
        session = _make_mock_session()
        result = await _default_general_handler(session, "random text")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_classify_mixed_case_message(self):
        router = IntentRouter()
        # "SELL" in uppercase should still match TRADE
        assert router.classify("SELL 0.5 ETH at market") == IntentType.TRADE

    def test_classify_message_with_leading_whitespace(self):
        router = IntentRouter()
        result = router.classify("   buy some BTC   ")
        assert result == IntentType.TRADE

    def test_classify_slash_command_with_leading_whitespace(self):
        router = IntentRouter()
        result = router.classify("  /portfolio  ")
        assert result == IntentType.PORTFOLIO

    def test_slash_commands_map_covers_all_expected_tokens(self):
        expected_tokens = {
            "trade", "buy", "sell", "order",
            "analyze", "analyse", "analysis", "chart",
            "portfolio", "balance", "positions", "pnl",
            "journal", "log", "note",
            "learn", "explain", "help",
            "permissions", "permission", "access", "role",
            "status", "health", "ping", "info",
        }
        actual_tokens = set(_SLASH_COMMANDS.keys())
        assert expected_tokens.issubset(actual_tokens)

    def test_register_and_route_integration(self):
        router = IntentRouter()
        call_log = []

        async def spy_handler(session, message, **kwargs):
            call_log.append(message)
            return "ok"

        router.register(IntentType.STATUS, spy_handler)
        intent, handler = router.route("/status")
        assert intent == IntentType.STATUS
        assert handler is spy_handler

"""Lokale control-service: de enige schakel tussen browser en tradingbot.

    Chrome Extension
            v
    control_service  (deze map -- HTTP, token-authenticatie, loopback-only)
            v
    bot.supervisor   (start/stopt en bewaakt het botproces)
            v
    run_trader_loop  (de handelsmotor)
            v
    Coinbase API

De reden voor deze scheiding: handelslogica en API-sleutels horen niet in
browsercode. De extension kent alleen HTTP-endpoints en ziet nooit een secret;
alles wat gevoelig is blijft in dit Python-proces op de eigen pc.

Het bestaande read-only dashboard (``dashboard/backend``) blijft volledig
ongewijzigd. Dat is bewust: daar geldt de harde regel dat geen enkel endpoint
iets schrijft of start, en die garantie zou vervallen als start/stop erbij zou
komen. Deze service draait daarom apart, op een eigen poort, achter een eigen
token.
"""

__all__ = ["config"]

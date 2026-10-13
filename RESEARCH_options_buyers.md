# Who makes money buying calls/puts? (research summary, Oct 12 2026)

## Bottom line
No broad, documented edge for buying options on mega-caps. Buyers as a group lose — mostly to bid/ask spreads and paying up for expensive volatility. The real edges are (a) volatility timing and (b) strong *stock* direction signals expressed through options.

## Where the money is lost
- Retail options traders (Nov 2019–Jun 2021): ~$1.14B trading losses + ~$4.13B hidden spread costs; losses concentrated in ATM calls expiring within a week. Quoted spreads ~12% (weeklies) to ~28% (slightly OTM). [Bryzgalova et al.](https://conference.nber.org/conf_papers/f163907/f163907.pdf)
- Around earnings, retail loses 5–9% (10–14% when a big move is already priced). [de Silva/Smith/So](https://quantpedia.com/how-retail-losses-money-in-option-trading/)
- Lottery-like (high-skew, cheap OTM) options are overpriced. [Boyer & Vorkink](https://optionmetrics.com/research/b-boyer-k-vorkink-stock-options-as-lotteries)

## Documented edges (need historical implied-vol data to test)
- Pre-earnings IV run-up: buy ATM straddle 3 days before earnings, exit before the report (+3.0% over 3 days, 1996–2010; needs 4–10 DTE to survive costs). [Alpha Architect](https://alphaarchitect.com/straddle-earnings-announcements-and-win/)
- Cheap vol: buy straddles when realized vol is high vs implied (~3.9%/mo long-short after costs). [BSIC](https://bsic.it/dislocations-historical-implied-volatility-indicators-volatility-trades/)
- NFLX historically moved more than implied on earnings 54% of the time. [IBKR/Market Chameleon](https://ibkrcampus.com/campus/traders-insight/securities/options/do-options-traders-tend-to-underestimate-nflx-earnings-moves-a-market-chameleon-analysis/)
- Weak/dead: post-earnings drift (≈0 after 2017), skew signal (not significant 2023–26), protective crash puts (negative).

## What profitable buyers avoid
Weeklies, slightly-OTM wide-spread strikes, buying right before announcements that already price a big move, lottery tickets. Buy implied vol when it's cheap vs realized.

## Our tests
- Momentum option buying (original bot): loses.
- Pullback calls (uptrend + RSI(2) dip): 63% win, +10.9%/trade, held up on newer data.
- Credit spreads SPY/QQQ: ~85% win, held up.
- Next: edge scanner across 13 tickers; start logging daily implied vol so volatility-timing edges can be tested in a few months.

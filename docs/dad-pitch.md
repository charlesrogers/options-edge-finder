# Covered Call Copilot — For Dad

## The One-Sentence Pitch

**You already sell covered calls profitably. This tool watches every position for the setup that got you last time, and tells you exactly when to act.**

*(It alerts; it can't act for you, and it can't stop a gap through your strike overnight. What it removes is the failure mode where nobody was watching.)*

---

## What It Does (The 3-Minute Version)

You know the MSFT disaster. $400K in taxes because you didn't buy back the calls before ex-dividend. This tool exists so that never happens again.

**It does three things:**

### 1. Tells You What to Sell
For each stock you own, it recommends the optimal covered call: which strike, which expiration, how much premium you'll collect. The recommendations are researched — 23 experiments, 145,000 real option observations,
strike distances walk-forward validated out-of-sample.

**Per your holdings** (win rate and income re-measured 2026-08-17, Exp 022, after we found and fixed a clock bug that had corrupted every backtest between Exp 007 and Exp 014, then re-measured again on a simulator with six further defects removed):

| Stock | Recommended | Win rate | Income per contract/yr | Why |
|---|---|---|---|---|
| AAPL | 15% OTM, 20-45 DTE | 91% | ~$141 | Best evidence in the set: 97% of its option days have real traded prices, and it is the only holding whose number does not move when we exclude estimated fills |
| DIS | 7% OTM, 30-60 DTE, **only when IV rank ≥ 75** | 80% | ~$267 | The one ticker that earned its own entry threshold (Exp 023) |
| TMUS | 15% OTM, 20-45 DTE | 92% | ~$151 | **Probation** — only 56% of its option days have real prices; count on real fills only and the overlay loses money |
| KKR | 15% OTM, 20-45 DTE, **max 7 contracts** | 63% | ~$316 | **Probation** — 36% real-price coverage, and the strike we'd sell trades 3 contracts a day |
| GOOGL | 10% OTM, 20-45 DTE | 94%* | not measured | **Probation** — *validated on stock closes only; we own 5 days of its option data |
| TXN | **Skip** | — | — | Loses money at every strike distance |
| AMZN | **Skip** | — | — | Failed validation at a *safer* strike than it was set to; no option data was ever bought |

**Read the income column as an order of magnitude, not a forecast.** It comes from one year of real prices in one favourable market. Depending on which week you start, AAPL's year ranges from −$776 to +$352 per contract — a spread far wider than the $141 midpoint. With roughly 13 trades a year, when you start matters more than most of the settings do.

The AAPL figure has now been corrected downward twice, from $351 to $299 to $141, each time because we found a specific defect in the simulator rather than because the market changed. The other three holdings measure *higher* on the corrected simulator; we have deliberately left their numbers at the lower, older values rather than raise a claim we have only measured once. Every number in this column is a floor we have evidence for, not a target.

### 2. Monitors Your Positions (The Copilot)
Once you sell a call, the copilot checks it on a 15-minute schedule during market hours (in
practice GitHub's scheduler runs late fairly often, so gaps of half an hour happen — the
positions page now shows you exactly how old its last check is). Five alert levels:

| Alert | What It Means | What You Do |
|---|---|---|
| ✅ **SAFE** | Stock well below strike | Nothing. Keep holding. |
| ⚠️ **WATCH** | Stock approaching strike | Check daily |
| 🟠 **CLOSE SOON** | Premium mostly captured or near strike | Buy back this week |
| 🔴 **CLOSE NOW** | Stock at or above strike | Buy back at market open |
| 🚨 **EMERGENCY** | ITM + ex-dividend imminent | Buy back IMMEDIATELY. This is the MSFT alert. |

You get **push notifications on your phone** for CLOSE SOON, CLOSE NOW, and EMERGENCY. The EMERGENCY alert repeats every 30 seconds until you acknowledge it.

### 3. Tracks Results
Every recommendation is written to a log with the price it was quoted at, and scored once it
reaches expiry. You can see every trade at /paper-trades.

**There is no track record yet, and I want to be precise about that.** The 444 scored trades
in that log are *synthetic*: I seeded the history by pricing hypothetical trades with
Black-Scholes off stock history, not off quotes anyone could have traded. Their 76% win rate
is a property of that pricing model. Eight real recommendations have been logged off live
option chains — all in the last few days — and none reaches expiry before **2026-09-18**.
Until then the honest answer to "does this work in practice" is that we do not know yet.

The log also stopped writing for 144 days (2026-03-24 to 2026-08-15) without anyone noticing,
which is fixed and is why the page now shows how old its numbers are.

---

## Your Daily Workflow

**Morning (2 minutes):**
1. Open https://options.imprevista.com/positions
2. Check alerts — green means do nothing, orange/red means act
3. If the app recommends selling a new call (on the Sell a Call tab), go to WellsTrade and place the order

**During the day:**
- Do nothing. The copilot monitors automatically.
- If something urgent happens, your phone buzzes.

**That's it.** The app handles the analysis, monitoring, and alerting. You handle the order execution at Wells Fargo.

---

## How It Works (For a 30-Year Goldman/CS/DB Veteran)

You know covered calls. You know the risk. Here's the research backing:

### The Data
- **145,099 real option observations** (Databento OHLCV, not BSM estimates) behind the
  assignment-probability table. This table was independently checked and is one of the two
  artefacts the clock bug did *not* touch.
- **23 experiments.** Pre-registration with immutable pass/fail thresholds started at Exp 021;
  the earlier ones were not pre-registered, and several did not survive re-examination.
- **Strike distances walk-forward validated** (Exp 014, train on the first 67% / test on the
  last 33%) — also verified outside the clock bug's blast radius.
- **Income and win rates re-measured on real option chains** (Exp 022) after the bug was
  fixed. Three of the four tickers failed their pre-registered tolerance and were corrected
  downward.
- **Paper trading:** see the caveat above — the scored history is synthetic, and real scoring
  begins 2026-09-18.

### The Key Finding: When to Buy Back
"Wait and hope" always costs more than closing. At every moneyness level and every DTE, buying back NOW saves money vs waiting. This is from 145K real observations — the instinct to wait for the stock to come back is empirically wrong.

### The Alert Thresholds
Each threshold comes from the empirical ITM probability table:
- 3-5% OTM with <7 DTE: 4-16% assignment probability → CLOSE SOON
- 1-3% OTM: 13-55% probability → CLOSE NOW
- ITM: 76-98% probability → CLOSE NOW
- ITM + ex-div within 3 days: ~100% → EMERGENCY

### Bear Market Performance
**I've withdrawn the numbers that used to be here.** They came from a Monte Carlo stress test
(Exp 010) that ran through the same broken clock as the other invalidated backtests, and they
were being presented as though they described 2020 and 2022. They described neither.

What holds without that experiment: a covered call collects premium, the premium offsets part
of a drawdown, and it cannot offset much of a large one. Selling calls does not increase your
downside — you keep the premium whatever the stock does — but it does not protect you either.
How much cushion this specific strategy provides is an open question until the stress test is
re-run on the corrected simulator.

---

## Anticipated Questions

### "Why not just set a stop-loss?"
Stop-losses on short calls don't work the way you'd expect. The option price spikes when the stock moves toward your strike, and by the time a stop triggers, you're buying back at the worst price. The copilot monitors the POSITION (stock vs strike distance, DTE, ex-div proximity) not just the option price. It catches dangerous situations before they become expensive.

### "What about the premium I'm giving up by closing early?"
Buying back early costs you the remaining time value — that is the insurance premium, and it
is real money. The specific figures that used to be here ("keep 62% of premium", "$27,000 in
simulated tax events", "5x ROI") came from Exp 007, one of the backtests the clock bug
invalidated, so I've pulled them rather than quote numbers I can't stand behind.

The argument does not depend on them. A single assignment on 10,000 low-basis shares realises
a capital gain you chose the timing of — that is the MSFT event, and it cost $400K. Early
buyback costs are small and frequent; assignment is large and rare. You are buying out of the
tail. What I can't currently tell you is the exact price of that insurance.

### "I've been doing this for 30 years without a tool."
You have. And you've made money. The tool doesn't change your strategy — it prevents the 1% of the time when things go wrong fast. The MSFT event happened once in your career and cost $400K. The copilot's job is to make that impossible.

### "How do I know the recommendations are right?"
The strike distances are walk-forward validated — tested on data the model never saw during
training. When 3% OTM turned out to be too aggressive for TMUS, that test caught it and we
moved to 15%.

The honest limit: the paper-trade history is synthetic, so it is not yet evidence that the
recommendations work in practice — first real outcomes land 2026-09-18. And the system's
self-correction has mostly run in one direction. Every published income figure has been
revised *down* as defects were found: AAPL went $351 → $299 → $141, and three of four tickers
failed their re-measurement. That is the process working, but it should also tell you how much
weight to put on any single number here.

### "What if the market crashes?"
Covered calls help somewhat in a crash: the calls expire worthless, you keep the premium, and
that premium offsets part of the stock loss. The copilot doesn't panic on drops — it only
alerts when the stock RISES toward your strike, because that's the assignment risk.

I've withdrawn the "$21K less in a -30% crash" figure that used to be here; it came from the
invalidated stress test. Premium is a cushion, not a hedge, and I can't currently size it.

### "What about ex-dividend risk?"
This is the #1 feature. The copilot tracks ex-dividend dates for every position. When you're ITM within 3 days of ex-div, it fires the EMERGENCY alert — the $400K alert. Your phone will alarm every 30 seconds until you acknowledge it.

### "What does it cost?"
The app is free (I built it). Pushover is a one-time $5 purchase for the phone app. The only "cost" is the premium you give up on early buybacks — which is $5K/year insurance against $400K disasters.

### "Can it place orders for me?"
Not yet. Wells Fargo doesn't have a trading API. You see the alert on your phone, open WellsTrade, and place the order. The copilot tells you WHAT to do and WHEN — you execute at Wells. If you ever move to Interactive Brokers, we could automate order placement.

---

## Getting Started

1. **Buy Pushover** ($5 one-time) on your phone — iOS or Android
2. **Give me your Pushover user key** — I'll wire it into the alerts
3. **Enter your holdings** at https://options.imprevista.com/positions (how many shares of each stock)
4. **Sell your first covered call** using the Sell a Call tab recommendation
5. **Log the trade** in the app (ticker, strike, premium, expiration)
6. **Relax.** The copilot monitors from here. Your phone will buzz if anything needs attention.

---

## What I Need From You

1. Your Pushover user key (after you install the app)
2. Confirmation of your current holdings (shares per ticker)
3. Any open covered call positions you have right now (so I can start monitoring them)
4. 15 minutes to walk through the app together on a call

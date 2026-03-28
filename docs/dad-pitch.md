# Covered Call Copilot — For Dad

## The One-Sentence Pitch

**You already sell covered calls profitably. This tool makes sure you never get called away again — and tells you exactly when to act.**

---

## What It Does (The 3-Minute Version)

You know the MSFT disaster. $400K in taxes because you didn't buy back the calls before ex-dividend. This tool exists so that never happens again.

**It does three things:**

### 1. Tells You What to Sell
For each stock you own, it recommends the optimal covered call: which strike, which expiration, how much premium you'll collect. The recommendations are researched — 14 experiments, 145,000 real option observations, walk-forward validated out-of-sample.

**Per your holdings:**
| Stock | Recommended | Expected Win Rate | Why |
|---|---|---|---|
| TMUS | 15% OTM, 20-45 DTE | 89% | Conservative — high win rate, moderate premium |
| KKR | 15% OTM, 20-45 DTE | 87% | Validated on 3yr of data, 0% test loss rate |
| DIS | 7% OTM, 30-60 DTE | 85% | Sweet spot for DIS volatility |
| AAPL | 15% OTM, 20-45 DTE | 96% | Ultra-conservative, nearly never loses |
| GOOGL | 10% OTM, 20-45 DTE | 94% | Walk-forward validated at 6% loss rate |
| TXN | **Skip** | — | Too volatile, loses at every OTM% |
| AMZN | 5% OTM, 20-45 DTE | 95% | Paper trading shows strong results |

### 2. Monitors Your Positions (The Copilot)
Once you sell a call, the copilot watches it every 15 minutes during market hours. Five alert levels:

| Alert | What It Means | What You Do |
|---|---|---|
| ✅ **SAFE** | Stock well below strike | Nothing. Keep holding. |
| ⚠️ **WATCH** | Stock approaching strike | Check daily |
| 🟠 **CLOSE SOON** | Premium mostly captured or near strike | Buy back this week |
| 🔴 **CLOSE NOW** | Stock at or above strike | Buy back at market open |
| 🚨 **EMERGENCY** | ITM + ex-dividend imminent | Buy back IMMEDIATELY. This is the MSFT alert. |

You get **push notifications on your phone** for CLOSE SOON, CLOSE NOW, and EMERGENCY. The EMERGENCY alert repeats every 30 seconds until you acknowledge it.

### 3. Tracks Results
Every recommendation is logged and scored automatically. Right now we have 386 scored paper trades: **81% win rate, +62% average P&L per trade.** You can see every trade, every outcome, every pattern — just like you'd review a portfolio's performance.

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
- **145,099 real option observations** (Databento OHLCV, not BSM estimates)
- **480,000 Monte Carlo paths** for optimal exit timing
- **14 experiments**, each pre-registered with immutable pass/fail thresholds
- **Walk-forward validated** — train on first 67% of data, test on last 33%
- **Paper trading** since March 2025 — 386 scored trades, all logged automatically

### The Key Finding: When to Buy Back
"Wait and hope" always costs more than closing. At every moneyness level and every DTE, buying back NOW saves money vs waiting. This is from 145K real observations — the instinct to wait for the stock to come back is empirically wrong.

### The Alert Thresholds
Each threshold comes from the empirical ITM probability table:
- 3-5% OTM with <7 DTE: 4-16% assignment probability → CLOSE SOON
- 1-3% OTM: 13-55% probability → CLOSE NOW
- ITM: 76-98% probability → CLOSE NOW
- ITM + ex-div within 3 days: ~100% → EMERGENCY

### Bear Market Performance
Monte Carlo stress test (10,000 paths per scenario):
- **Sharp crash (-30%):** Covered calls + copilot lose 22% vs 28.5% stock-only. The premium cushion saves ~$21K per 1,000 shares.
- **Sideways market:** Stock -0.3%, covered calls +1.3%. This is the sweet spot.
- **The strategy never amplifies losses.** In every scenario, it matches or beats holding stock alone.

---

## Anticipated Questions

### "Why not just set a stop-loss?"
Stop-losses on short calls don't work the way you'd expect. The option price spikes when the stock moves toward your strike, and by the time a stop triggers, you're buying back at the worst price. The copilot monitors the POSITION (stock vs strike distance, DTE, ex-div proximity) not just the option price. It catches dangerous situations before they become expensive.

### "What about the premium I'm giving up by closing early?"
On average, you keep 62% of premium on winning trades. The 38% you "give up" is the insurance cost — it prevents the rare catastrophic losses. The copilot saved $27,000 in simulated tax events on AAPL alone. The math: $5K/year in early buyback costs vs $27K+ in avoided tax catastrophes. 5x ROI on the insurance.

### "I've been doing this for 30 years without a tool."
You have. And you've made money. The tool doesn't change your strategy — it prevents the 1% of the time when things go wrong fast. The MSFT event happened once in your career and cost $400K. The copilot's job is to make that impossible.

### "How do I know the recommendations are right?"
Every recommendation is paper-traded and scored. You can see the full history at /paper-trades — 386 trades, 81% win rate. The strategies are walk-forward validated (tested on data the model never saw during training). When we found that 3% OTM was too aggressive for TMUS, the walk-forward test caught it and we adjusted to 15%. The system corrects itself.

### "What if the market crashes?"
Covered calls help in a crash — the calls expire worthless (you keep the premium) and the premium cushions your stock loss. In our Monte Carlo stress test, a -30% crash costs $21K less with covered calls than without them. The copilot doesn't panic on stock drops — it only alerts when the stock RISES toward your strike.

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

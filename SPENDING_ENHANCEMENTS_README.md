# Spending Tracker Enhancements

## Overview
Your monthly spending reports now include **10 major improvements** that make them more actionable, insightful, and visually appealing.

## What's New

### 1. 🚨 Outlier Detection & One-Time Expense Flagging
- **Automatically detects** large one-time expenses (>$500) like insurance payments
- Shows **normalized spending** excluding outliers
- Compares normalized vs actual totals to avoid misleading trends

**Example:**
```
⚠️ UNUSUAL TRANSACTIONS THIS MONTH
• SECURITY NATIONAL INSU: $3,073.00 (Bills & Utilities)

Excluding large one-time expenses:
Normalized spending: $2,273.00 (was $5,346.00)
vs Last Month: $2,273.00 vs $2,142.00 = +6.1%
```

---

### 2. 💳 Net vs Gross Spending Display
- Shows **gross spending** (total purchases)
- Subtracts **refunds/returns**
- Displays **net spending** (what you actually spent)
- Calculates your **return rate** percentage

**Example:**
```
GROSS SPENDING: $6,154.34
REFUNDS/RETURNS: -$808.19 (3 transactions)
NET SPENDING: $5,346.15

💡 You returned 13.1% of purchases this month
```

---

### 3. 📊 Fixed vs Discretionary Spending Split
- **Fixed/Recurring:** Insurance, subscriptions, utilities (can't easily change)
- **Variable/Discretionary:** Groceries, dining, shopping (where you have control)
- Helps you understand what you can actually optimize

**Example:**
```
FIXED/RECURRING: $3,233 (60.5%)
VARIABLE/DISCRETIONARY: $2,113 (39.5%) — where you have control
```

---

### 4. 📈 3-Month Trend Analysis
- **Rolling 3-month average** with mini bar chart
- **Trend indicator:** Increasing/Decreasing/Stable
- Shows spending pattern over time

**Example:**
```
3-MONTH SPENDING TREND
[Bar chart showing March, April, May]
3-Month Average: $2,172/month
Trend: ↑ Increasing (+3.9% vs 3-mo ago)
```

---

### 5. 💡 Actionable Insights & Recommendations

#### ✓ WINS (What's going well)
- Foreign spending down 95%
- Groceries down 53%

#### ⚠️ WATCH (Areas of concern)
- Food & Dining up 39% — mostly delivery
- Top culprit: Uber Eats $99.79 (single order)

#### 💰 POTENTIAL SAVINGS
- Canva subscription cancelled — saving $15.73/mo ($188.76/year)
- Consider switching to free banking

---

### 6. 🔍 Category Deep Dives
- **Breaks down** Food & Dining into:
  - Restaurant sit-down
  - Delivery orders
  - Quick service/coffee
- Shows **average per visit**
- Highlights **spending patterns**

**Example:**
```
FOOD & DINING BREAKDOWN: $582.34
• Restaurant sit-down: $334.91 (57%) — 4 visits
• Delivery: $99.79 (17%) — 1 order
• Quick service/coffee: $147.64 (25%) — 8 visits

💡 Avg restaurant visit = $83.73 (up from $52 in April)
```

---

### 7. 💳 Subscription Health Check
- **Audits all subscriptions** for usage
- Flags **unused** or **underutilized** subscriptions
- Calculates **potential savings** if cancelled
- Color-coded status indicators

**Example:**
```
SUBSCRIPTION HEALTH CHECK
✓ Amazon Prime: $11.29/mo — used 6x this month
✓ Rogers Phone: $55.64/mo — essential
⚠️ Costco: $15.99/mo — visited 0x this month
  └─ Not used this month — consider canceling

💰 Potential savings: $15.99/mo ($191.88/year)
```

---

### 8. 🎯 Budget Tracking (Optional)
- Set **custom budgets** per category
- Visual **progress bars** showing % used
- **Color-coded alerts:** Green (on track), Yellow (near limit), Red (over budget)
- Overall budget summary

**Setup:** Edit `budget_config.json` to set your monthly budgets.

**Example:**
```
BUDGET TRACKING
Groceries: $348 / $500 budget (70% used) ✓
Dining Out: $582 / $400 budget (145% over) ❌
Shopping: $365 / $300 budget (122% over) ⚠️

Overall: $2,273 / $2,500 monthly budget (91%) ✓
```

---

### 9. ⏭️ Forward-Looking Alerts
- **Predicts upcoming recurring charges** for next month
- Shows **annual renewals** based on historical patterns
- Helps you **plan for expected expenses**

**Example:**
```
UPCOMING IN NEXT MONTH
• Rogers Phone Bill: $55.64 (Monthly)
• Amazon Prime: $11.29 (Monthly)
• Costco Membership: $63.99 (Annual)
```

---

### 10. 🎨 Enhanced HTML Visualizations
- **Mini bar charts** for trend comparison
- **Color-coded sections** for visual hierarchy
- **Progress bars** for budgets and spending
- **Responsive design** for mobile/desktop viewing
- **Professional styling** with consistent branding

---

## How to Enable

All enhancements are **automatically enabled** when you run the spending tracker. The system will:

1. ✅ Auto-detect outliers and normalize spending
2. ✅ Calculate net vs gross automatically
3. ✅ Generate insights based on patterns
4. ✅ Show 3-month trends if historical data exists
5. ✅ Audit subscriptions for usage
6. ✅ Predict upcoming charges

### Optional: Budget Tracking

To enable budget tracking:

1. Edit `budget_config.json`
2. Set your monthly budget for each category
3. Set `"enable_budget_alerts": true`
4. Next report will include budget tracking

**Example budget_config.json:**
```json
{
  "monthly_budgets": {
    "Groceries": 500,
    "Food & Dining": 400,
    "Shopping": 300,
    "Transport": 200,
    "Entertainment": 150
  },
  "total_monthly_budget": 2500,
  "enable_budget_alerts": true
}
```

---

## Technical Details

### New Files Added

1. **`spending_enhancements.py`** — Core analytics engine
   - Outlier detection
   - Recurring vs discretionary split
   - Actionable insights generation
   - 3-month trend calculation
   - Category deep dives
   - Subscription auditing
   - Net spending calculation
   - Upcoming charge predictions

2. **`spending_html_enhanced.py`** — HTML template generators
   - All 10 visualization sections
   - Responsive table-based layouts
   - Email-compatible styling

3. **`budget_config.json`** — Optional budget configuration

### Integration

The main `spending_tracker.py` now:
- Imports enhanced analytics modules
- Generates all new sections automatically
- Falls back gracefully if enhancements unavailable
- Maintains backward compatibility

---

## Testing

To test the enhancements:

```bash
cd ~/portfolio-monitor

# Test with current month data
python3 spending_tracker.py --now

# Or regenerate a specific month to see new format
python3 spending_tracker.py --month 2026-05
```

---

## Benefits

### Before (Old Report):
- Just numbers and categories
- No context or recommendations
- Outliers skewed trends
- No way to track progress
- Reactive (what happened)

### After (Enhanced Report):
- **Actionable insights** (what to do)
- **Normalized trends** (accurate patterns)
- **Budget tracking** (stay on target)
- **Subscription audit** (find savings)
- **Forward-looking** (plan ahead)
- **Visual progress** (easy to understand)

---

## Support

If you encounter any issues:

1. Check the log: `spending_tracker.log`
2. Verify files exist: `spending_enhancements.py`, `spending_html_enhanced.py`
3. Test basic functionality: `python3 spending_tracker.py --now`

## Future Enhancements (Potential)

- 📱 SMS alerts for budget overruns
- 📊 Year-over-year comparisons
- 🤖 ML-based anomaly detection
- 💰 Savings goal tracking
- 📈 Interactive charts (if viewing in web app)
- 🏆 Spending challenges/gamification

---

**Last Updated:** June 1, 2026  
**Version:** 2.0 — All 10 Enhancements Implemented

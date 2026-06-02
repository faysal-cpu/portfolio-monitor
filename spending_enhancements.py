#!/usr/bin/env python3
"""
Spending Tracker Enhancements
Advanced analytics and insights for monthly spending reports
"""

from typing import List, Dict, Any, Tuple, Optional
from collections import defaultdict
from datetime import datetime, timedelta
import re


class Transaction:
    """Transaction class stub for type hints"""
    def __init__(self, date, description, amount, merchant, source, raw_data):
        self.date = date
        self.description = description
        self.amount = amount
        self.merchant = merchant
        self.source = source
        self.raw_data = raw_data
        self.category = None
        self.is_subscription = False


def detect_outliers(transactions: List[Transaction], threshold: float = 500.0) -> Dict[str, Any]:
    """Detect one-time large expenses that skew monthly averages

    Returns:
        - outlier_transactions: List of large one-time expenses
        - normalized_total: Total spending excluding outliers
        - outlier_total: Sum of all outliers
    """
    positive_txs = [tx for tx in transactions if tx.amount > 0]
    outliers = []

    for tx in positive_txs:
        if tx.amount >= threshold:
            # Check if it's likely one-time (not a subscription)
            if not tx.is_subscription:
                outliers.append({
                    'merchant': tx.merchant,
                    'amount': tx.amount,
                    'date': tx.date,
                    'category': tx.category or 'Other',
                    'description': tx.description
                })

    outlier_total = sum(o['amount'] for o in outliers)
    regular_total = sum(tx.amount for tx in positive_txs if tx.amount < threshold)

    return {
        'outliers': outliers,
        'outlier_total': outlier_total,
        'normalized_total': regular_total,
        'gross_total': sum(tx.amount for tx in positive_txs)
    }


def calculate_recurring_vs_discretionary(transactions: List[Transaction]) -> Dict[str, Any]:
    """Split spending into fixed/recurring vs variable/discretionary

    Fixed: Insurance, subscriptions, utilities, rent
    Discretionary: Groceries, dining, shopping, entertainment
    """
    fixed_categories = ['Bills & Utilities']
    discretionary_categories = ['Groceries', 'Food & Dining', 'Shopping', 'Entertainment', 'Travel', 'Transport']

    fixed_total = 0
    discretionary_total = 0
    other_total = 0

    fixed_details = []
    discretionary_details = []

    for tx in transactions:
        if tx.amount <= 0:  # Skip refunds
            continue

        category = tx.category or 'Other'

        if category in fixed_categories or tx.is_subscription:
            fixed_total += tx.amount
            fixed_details.append({
                'merchant': tx.merchant,
                'amount': tx.amount,
                'category': category,
                'is_subscription': tx.is_subscription
            })
        elif category in discretionary_categories:
            discretionary_total += tx.amount
            discretionary_details.append({
                'merchant': tx.merchant,
                'amount': tx.amount,
                'category': category
            })
        else:
            other_total += tx.amount

    return {
        'fixed_total': fixed_total,
        'discretionary_total': discretionary_total,
        'other_total': other_total,
        'fixed_details': fixed_details,
        'discretionary_details': discretionary_details
    }


def generate_actionable_insights(
    transactions: List[Transaction],
    prev_month_data: Optional[Dict],
    outlier_data: Dict
) -> Dict[str, List[str]]:
    """Generate wins, warnings, and savings recommendations"""

    wins = []
    warnings = []
    savings = []

    positive_txs = [tx for tx in transactions if tx.amount > 0]
    negative_txs = [tx for tx in transactions if tx.amount < 0]

    # Category totals for current month
    category_totals = defaultdict(float)
    for tx in positive_txs:
        category_totals[tx.category or 'Other'] += tx.amount

    # Compare with previous month
    if prev_month_data:
        prev_categories = prev_month_data.get('category_totals', {})

        # Check for significant improvements
        for category in ['Food & Dining', 'Shopping', 'Transport', 'Entertainment']:
            current = category_totals.get(category, 0)
            previous = prev_categories.get(category, 0)

            if previous > 0 and current < previous * 0.7:  # 30% reduction
                pct_change = ((current - previous) / previous) * 100
                wins.append(f"{category} down {abs(pct_change):.0f}% (${previous:.0f} → ${current:.0f})")

        # Check foreign spending
        current_foreign = sum(tx.amount for tx in positive_txs if is_foreign_tx(tx))
        prev_foreign = prev_month_data.get('foreign_total', 0)
        if prev_foreign > 100 and current_foreign < prev_foreign * 0.5:
            wins.append(f"Foreign spending down {((current_foreign - prev_foreign) / prev_foreign * 100):.0f}% (${prev_foreign:.0f} → ${current_foreign:.0f})")

        # Check for increases
        for category in ['Food & Dining', 'Shopping', 'Entertainment']:
            current = category_totals.get(category, 0)
            previous = prev_categories.get(category, 0)

            if previous > 0 and current > previous * 1.3:  # 30% increase
                pct_change = ((current - previous) / previous) * 100

                # Find top culprit
                cat_txs = [tx for tx in positive_txs if (tx.category or 'Other') == category]
                top_tx = max(cat_txs, key=lambda x: x.amount) if cat_txs else None

                if top_tx:
                    warnings.append(f"{category} up {pct_change:.0f}% (${previous:.0f} → ${current:.0f}) — Top: {top_tx.merchant} ${top_tx.amount:.2f}")
                else:
                    warnings.append(f"{category} up {pct_change:.0f}% (${previous:.0f} → ${current:.0f})")

    # Check for large single transactions
    for tx in positive_txs:
        if tx.amount > 100 and not tx.is_subscription:
            category = tx.category or 'Other'
            if category in ['Food & Dining', 'Shopping', 'Entertainment']:
                if tx.amount > 150:
                    warnings.append(f"Large {category} purchase: {tx.merchant} ${tx.amount:.2f}")

    # Check for refunded subscriptions (savings opportunity)
    for tx in negative_txs:
        if 'subscription' in tx.description.lower() or 'membership' in tx.description.lower():
            annual_savings = abs(tx.amount) * 12
            savings.append(f"{tx.merchant} cancelled — saving ${abs(tx.amount):.2f}/mo (${annual_savings:.2f}/year)")

    # Check high-frequency low-value purchases (coffee, delivery fees)
    delivery_keywords = ['uber eats', 'doordash', 'skip', 'delivery']
    delivery_txs = [tx for tx in positive_txs
                    if any(kw in tx.merchant.lower() for kw in delivery_keywords)]
    if len(delivery_txs) >= 4:
        delivery_total = sum(tx.amount for tx in delivery_txs)
        warnings.append(f"{len(delivery_txs)} delivery orders this month = ${delivery_total:.2f} in fees")

    return {
        'wins': wins[:5],  # Top 5
        'warnings': warnings[:5],
        'savings': savings[:3]
    }


def is_foreign_tx(tx: Transaction) -> bool:
    """Check if transaction is foreign"""
    country_code = tx.raw_data.get('Merchant Country Code', '').upper().strip()
    if country_code and country_code not in ['CAN', '']:
        return True

    foreign_keywords = ['USD', 'EUR', 'DUBAI', 'MEXICO', 'USA', 'MIAMI']
    text = (tx.description + ' ' + tx.merchant).upper()
    return any(kw in text for kw in foreign_keywords)


def calculate_3month_trend(history: Dict, current_year: int, current_month: int) -> Dict[str, Any]:
    """Calculate 3-month rolling average and trend"""

    months_data = []

    for i in range(3):
        month_offset = current_month - i
        year = current_year

        while month_offset <= 0:
            month_offset += 12
            year -= 1

        month_key = f"{year}-{month_offset:02d}"
        if month_key in history:
            months_data.append({
                'month': month_offset,
                'year': year,
                'total': history[month_key]['total_spent'],
                'key': month_key
            })

    if len(months_data) < 2:
        return {'has_trend': False}

    # Calculate average
    avg_spending = sum(m['total'] for m in months_data) / len(months_data)

    # Determine trend (compare most recent to oldest)
    if len(months_data) >= 2:
        recent = months_data[0]['total']
        oldest = months_data[-1]['total']

        if recent > oldest * 1.05:
            trend = 'increasing'
            pct = ((recent - oldest) / oldest) * 100
        elif recent < oldest * 0.95:
            trend = 'decreasing'
            pct = ((oldest - recent) / oldest) * 100
        else:
            trend = 'stable'
            pct = 0
    else:
        trend = 'stable'
        pct = 0

    return {
        'has_trend': True,
        'months_data': months_data,
        'avg_spending': avg_spending,
        'trend': trend,
        'trend_pct': pct
    }


def analyze_category_deep_dive(transactions: List[Transaction], category: str) -> Dict[str, Any]:
    """Deep dive into a specific category (e.g., Food & Dining)"""

    cat_txs = [tx for tx in transactions if (tx.category or 'Other') == category and tx.amount > 0]

    if not cat_txs:
        return {'has_data': False}

    total = sum(tx.amount for tx in cat_txs)
    count = len(cat_txs)
    avg_per_visit = total / count if count > 0 else 0

    # Subcategorize (for Food & Dining)
    if category == 'Food & Dining':
        delivery_keywords = ['uber eats', 'doordash', 'skip', 'delivery']
        quick_keywords = ['starbucks', 'tim hortons', 'coffee', 'subway', 'mcdonald']

        delivery_txs = [tx for tx in cat_txs if any(kw in tx.merchant.lower() for kw in delivery_keywords)]
        quick_txs = [tx for tx in cat_txs if any(kw in tx.merchant.lower() for kw in quick_keywords)]
        sitdown_txs = [tx for tx in cat_txs if tx not in delivery_txs and tx not in quick_txs]

        return {
            'has_data': True,
            'total': total,
            'count': count,
            'avg_per_visit': avg_per_visit,
            'subcategories': {
                'sit_down': {
                    'total': sum(tx.amount for tx in sitdown_txs),
                    'count': len(sitdown_txs),
                    'pct': (sum(tx.amount for tx in sitdown_txs) / total * 100) if total > 0 else 0
                },
                'delivery': {
                    'total': sum(tx.amount for tx in delivery_txs),
                    'count': len(delivery_txs),
                    'pct': (sum(tx.amount for tx in delivery_txs) / total * 100) if total > 0 else 0
                },
                'quick_service': {
                    'total': sum(tx.amount for tx in quick_txs),
                    'count': len(quick_txs),
                    'pct': (sum(tx.amount for tx in quick_txs) / total * 100) if total > 0 else 0
                }
            }
        }

    # Generic breakdown for other categories
    return {
        'has_data': True,
        'total': total,
        'count': count,
        'avg_per_visit': avg_per_visit
    }


def audit_subscriptions(subscriptions: List[Dict], transactions: List[Transaction]) -> Dict[str, Any]:
    """Audit subscriptions for usage and savings opportunities"""

    audited = []
    total_monthly = 0
    potential_savings = 0

    for sub in subscriptions:
        merchant_normalized = sub['normalized'].upper()
        monthly_amt = sub['avg_amount']
        total_monthly += monthly_amt

        # Check usage this month
        usage_count = sum(1 for tx in transactions
                         if merchant_normalized in tx.merchant.upper() and tx.amount > 0)

        # Determine status
        is_essential = any(kw in merchant_normalized for kw in ['ROGERS', 'INSURANCE', 'PHONE', 'INTERNET'])
        is_unused = usage_count == 0 and not is_essential
        is_minimal = usage_count <= 1 and not is_essential

        status = 'essential' if is_essential else ('unused' if is_unused else ('minimal' if is_minimal else 'active'))

        if is_unused or is_minimal:
            potential_savings += monthly_amt

        audited.append({
            'merchant': sub['merchant'],
            'monthly_amt': monthly_amt,
            'annual_cost': monthly_amt * 12,
            'usage_count': usage_count,
            'status': status
        })

    return {
        'subscriptions': audited,
        'total_monthly': total_monthly,
        'potential_savings': potential_savings,
        'potential_annual_savings': potential_savings * 12
    }


def calculate_net_spending(transactions: List[Transaction]) -> Dict[str, Any]:
    """Calculate gross spending, refunds, and net spending"""

    positive_txs = [tx for tx in transactions if tx.amount > 0]
    negative_txs = [tx for tx in transactions if tx.amount < 0]

    gross_spending = sum(tx.amount for tx in positive_txs)
    total_refunds = abs(sum(tx.amount for tx in negative_txs))
    net_spending = gross_spending - total_refunds

    return_rate = (total_refunds / gross_spending * 100) if gross_spending > 0 else 0

    # Top refunds
    refund_details = sorted(
        [{'merchant': tx.merchant, 'amount': abs(tx.amount), 'date': tx.date}
         for tx in negative_txs],
        key=lambda x: x['amount'],
        reverse=True
    )[:5]

    return {
        'gross_spending': gross_spending,
        'total_refunds': total_refunds,
        'net_spending': net_spending,
        'return_rate': return_rate,
        'refund_count': len(negative_txs),
        'refund_details': refund_details
    }


def predict_upcoming_charges(subscriptions: List[Dict], current_month: int) -> List[Dict]:
    """Predict upcoming recurring charges for next month"""

    upcoming = []
    next_month = (current_month % 12) + 1

    for sub in subscriptions:
        merchant = sub['merchant']
        monthly_amt = sub['avg_amount']

        # Check if this is an annual subscription
        if sub['occurrences'] <= 2:  # Appears 1-2 times in 6 months = likely annual
            upcoming.append({
                'merchant': merchant,
                'amount': monthly_amt,
                'type': 'annual',
                'confidence': 'medium'
            })
        else:
            # Monthly subscription
            upcoming.append({
                'merchant': merchant,
                'amount': monthly_amt,
                'type': 'monthly',
                'confidence': 'high'
            })

    return sorted(upcoming, key=lambda x: x['amount'], reverse=True)[:5]

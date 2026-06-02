#!/usr/bin/env python3
"""
Enhanced HTML Email Templates for Spending Reports
Includes all 10 improvements with beautiful visualizations
"""

from typing import List, Dict, Any, Optional
from datetime import datetime


def generate_mini_bar_chart(values: List[float], labels: List[str], max_width: int = 200) -> str:
    """Generate inline HTML bar chart"""
    if not values or not labels or len(values) != len(labels):
        return ""

    max_val = max(values) if values else 1

    html = '<table style="width: 100%; border-collapse: collapse; margin: 10px 0;">'
    for val, label in zip(values, labels):
        bar_width = int((val / max_val) * max_width) if max_val > 0 else 0
        html += f'''
        <tr>
            <td style="padding: 4px 8px 4px 0; font-size: 12px; width: 80px;">{label}</td>
            <td style="padding: 4px 0;">
                <div style="background: #667eea; height: 20px; width: {bar_width}px; border-radius: 3px;"></div>
            </td>
            <td style="padding: 4px 0 4px 8px; font-size: 12px; font-weight: 600; color: #2d3748;">${val:,.0f}</td>
        </tr>
        '''
    html += '</table>'
    return html


def generate_outlier_section(outlier_data: Dict, prev_total: Optional[float] = None) -> str:
    """Generate HTML for outlier detection section"""
    if not outlier_data['outliers']:
        return ""

    outliers = outlier_data['outliers']
    outlier_total = outlier_data['outlier_total']
    normalized_total = outlier_data['normalized_total']
    gross_total = outlier_data['gross_total']

    html = '''
    <tr>
        <td style="padding: 30px;">
            <table border="0" cellpadding="15" cellspacing="0" width="100%" style="background-color: #fff3cd; border-left: 4px solid #f59e0b; border-radius: 8px;">
                <tr>
                    <td>
                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                            <tr>
                                <td style="font-size: 14px; font-weight: bold; color: #92400e; padding-bottom: 10px;">
                                    ⚠️ UNUSUAL TRANSACTIONS THIS MONTH
                                </td>
                            </tr>
    '''

    # List outliers
    for outlier in outliers:
        html += f'''
                            <tr>
                                <td style="font-size: 13px; color: #78350f; padding: 5px 0;">
                                    • {outlier['merchant']}: <strong>${outlier['amount']:,.2f}</strong> ({outlier['category']})
                                </td>
                            </tr>
        '''

    # Show normalized comparison
    html += f'''
                            <tr>
                                <td style="font-size: 13px; color: #78350f; padding-top: 10px; border-top: 1px solid #fde68a; margin-top: 10px;">
                                    <strong>Excluding large one-time expenses:</strong><br>
                                    Normalized spending: <strong>${normalized_total:,.2f}</strong> (was ${gross_total:,.2f})
                                </td>
                            </tr>
    '''

    if prev_total:
        normalized_change = normalized_total - prev_total
        normalized_pct = (normalized_change / prev_total * 100) if prev_total > 0 else 0
        html += f'''
                            <tr>
                                <td style="font-size: 13px; color: #78350f;">
                                    vs Last Month: <strong>${normalized_total:,.2f}</strong> vs <strong>${prev_total:,.2f}</strong> = {normalized_pct:+.1f}%
                                </td>
                            </tr>
        '''

    html += '''
                        </table>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
    '''

    return html


def generate_net_spending_section(net_data: Dict) -> str:
    """Generate net vs gross spending section"""
    html = f'''
    <tr>
        <td style="padding: 0 30px 20px 30px;">
            <table border="0" cellpadding="15" cellspacing="0" width="100%" style="background-color: #f0f9ff; border-left: 4px solid #0284c7; border-radius: 8px;">
                <tr>
                    <td>
                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                            <tr>
                                <td style="font-size: 13px; color: #0c4a6e; padding-bottom: 8px;">
                                    <strong>GROSS SPENDING:</strong> ${net_data['gross_spending']:,.2f}
                                </td>
                            </tr>
                            <tr>
                                <td style="font-size: 13px; color: #0c4a6e; padding-bottom: 8px;">
                                    <strong>REFUNDS/RETURNS:</strong> -${net_data['total_refunds']:,.2f} ({net_data['refund_count']} transactions)
                                </td>
                            </tr>
                            <tr>
                                <td style="font-size: 14px; font-weight: bold; color: #0c4a6e; padding-top: 8px; border-top: 2px solid #bae6fd;">
                                    <strong>NET SPENDING:</strong> ${net_data['net_spending']:,.2f}
                                </td>
                            </tr>
    '''

    if net_data['return_rate'] > 5:
        html += f'''
                            <tr>
                                <td style="font-size: 12px; color: #0c4a6e; padding-top: 8px;">
                                    💡 You returned {net_data['return_rate']:.1f}% of purchases this month
                                </td>
                            </tr>
        '''

    html += '''
                        </table>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
    '''

    return html


def generate_recurring_vs_discretionary_section(split_data: Dict) -> str:
    """Generate recurring vs discretionary breakdown"""
    total = split_data['fixed_total'] + split_data['discretionary_total'] + split_data['other_total']
    fixed_pct = (split_data['fixed_total'] / total * 100) if total > 0 else 0
    disc_pct = (split_data['discretionary_total'] / total * 100) if total > 0 else 0

    html = f'''
    <tr>
        <td style="padding: 0 30px 20px 30px;">
            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                <tr>
                    <td style="font-size: 11px; font-weight: bold; letter-spacing: 1px; text-transform: uppercase; color: #6c757d; padding-bottom: 15px; border-bottom: 2px solid #e9ecef;">
                        SPENDING TYPE BREAKDOWN
                    </td>
                </tr>
            </table>
        </td>
    </tr>
    <tr>
        <td style="padding: 0 30px 10px 30px;">
            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                <tr>
                    <td width="48%" style="background-color: #fef3c7; padding: 15px; border-radius: 8px; border-left: 4px solid #f59e0b;">
                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                            <tr>
                                <td style="font-size: 11px; font-weight: bold; color: #78350f; padding-bottom: 8px;">
                                    FIXED/RECURRING
                                </td>
                            </tr>
                            <tr>
                                <td style="font-size: 24px; font-weight: bold; color: #92400e;">
                                    ${split_data['fixed_total']:,.2f}
                                </td>
                            </tr>
                            <tr>
                                <td style="font-size: 12px; color: #92400e;">
                                    {fixed_pct:.1f}% of spending
                                </td>
                            </tr>
                        </table>
                    </td>
                    <td width="4%"></td>
                    <td width="48%" style="background-color: #dbeafe; padding: 15px; border-radius: 8px; border-left: 4px solid #0284c7;">
                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                            <tr>
                                <td style="font-size: 11px; font-weight: bold; color: #0c4a6e; padding-bottom: 8px;">
                                    VARIABLE/DISCRETIONARY
                                </td>
                            </tr>
                            <tr>
                                <td style="font-size: 24px; font-weight: bold; color: #075985;">
                                    ${split_data['discretionary_total']:,.2f}
                                </td>
                            </tr>
                            <tr>
                                <td style="font-size: 12px; color: #075985;">
                                    {disc_pct:.1f}% of spending — where you have control
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
    '''

    return html


def generate_insights_section(insights: Dict) -> str:
    """Generate actionable insights section"""
    if not insights['wins'] and not insights['warnings'] and not insights['savings']:
        return ""

    html = '''
    <tr>
        <td style="padding: 30px;">
            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                <tr>
                    <td style="font-size: 16px; font-weight: bold; color: #1e293b; padding-bottom: 15px;">
                        💡 THIS MONTH'S INSIGHTS
                    </td>
                </tr>
            </table>
    '''

    # Wins
    if insights['wins']:
        html += '''
            <table border="0" cellpadding="12" cellspacing="0" width="100%" style="background-color: #f0fdf4; border-left: 4px solid #22c55e; border-radius: 8px; margin-bottom: 15px;">
                <tr>
                    <td>
                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                            <tr>
                                <td style="font-size: 13px; font-weight: bold; color: #14532d; padding-bottom: 8px;">
                                    ✓ WINS
                                </td>
                            </tr>
        '''
        for win in insights['wins']:
            html += f'''
                            <tr>
                                <td style="font-size: 12px; color: #166534; padding: 3px 0;">
                                    • {win}
                                </td>
                            </tr>
            '''
        html += '''
                        </table>
                    </td>
                </tr>
            </table>
        '''

    # Warnings
    if insights['warnings']:
        html += '''
            <table border="0" cellpadding="12" cellspacing="0" width="100%" style="background-color: #fff7ed; border-left: 4px solid #f97316; border-radius: 8px; margin-bottom: 15px;">
                <tr>
                    <td>
                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                            <tr>
                                <td style="font-size: 13px; font-weight: bold; color: #7c2d12; padding-bottom: 8px;">
                                    ⚠️ WATCH
                                </td>
                            </tr>
        '''
        for warning in insights['warnings']:
            html += f'''
                            <tr>
                                <td style="font-size: 12px; color: #9a3412; padding: 3px 0;">
                                    • {warning}
                                </td>
                            </tr>
            '''
        html += '''
                        </table>
                    </td>
                </tr>
            </table>
        '''

    # Savings
    if insights['savings']:
        html += '''
            <table border="0" cellpadding="12" cellspacing="0" width="100%" style="background-color: #ede9fe; border-left: 4px solid #a855f7; border-radius: 8px;">
                <tr>
                    <td>
                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                            <tr>
                                <td style="font-size: 13px; font-weight: bold; color: #581c87; padding-bottom: 8px;">
                                    💰 POTENTIAL SAVINGS
                                </td>
                            </tr>
        '''
        for saving in insights['savings']:
            html += f'''
                            <tr>
                                <td style="font-size: 12px; color: #6b21a8; padding: 3px 0;">
                                    • {saving}
                                </td>
                            </tr>
            '''
        html += '''
                        </table>
                    </td>
                </tr>
            </table>
        '''

    html += '''
        </td>
    </tr>
    '''

    return html


def generate_3month_trend_section(trend_data: Dict) -> str:
    """Generate 3-month trend chart"""
    if not trend_data.get('has_trend'):
        return ""

    months = trend_data['months_data']
    avg = trend_data['avg_spending']
    trend = trend_data['trend']
    pct = trend_data['trend_pct']

    # Generate labels and values for mini chart
    labels = [f"{m['year']}-{m['month']:02d}" for m in reversed(months)]
    values = [m['total'] for m in reversed(months)]

    trend_icon = "↑" if trend == "increasing" else ("↓" if trend == "decreasing" else "→")
    trend_color = "#dc2626" if trend == "increasing" else ("#22c55e" if trend == "decreasing" else "#64748b")

    html = f'''
    <tr>
        <td style="padding: 0 30px 20px 30px;">
            <table border="0" cellpadding="15" cellspacing="0" width="100%" style="background-color: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0;">
                <tr>
                    <td>
                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                            <tr>
                                <td style="font-size: 13px; font-weight: bold; color: #1e293b; padding-bottom: 10px;">
                                    📈 3-MONTH SPENDING TREND
                                </td>
                            </tr>
                            <tr>
                                <td>
                                    {generate_mini_bar_chart(values, labels)}
                                </td>
                            </tr>
                            <tr>
                                <td style="font-size: 13px; color: #475569; padding-top: 10px;">
                                    <strong>3-Month Average:</strong> ${avg:,.2f}/month
                                </td>
                            </tr>
                            <tr>
                                <td style="font-size: 13px; color: {trend_color}; font-weight: 600;">
                                    <strong>Trend:</strong> {trend_icon} {trend.capitalize()} ({pct:.1f}% vs 3-mo ago)
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
    '''

    return html


def generate_category_deep_dive_section(deep_dive: Dict, category: str) -> str:
    """Generate category deep dive section"""
    if not deep_dive.get('has_data'):
        return ""

    html = f'''
    <tr>
        <td style="padding: 0 30px 20px 30px;">
            <table border="0" cellpadding="12" cellspacing="0" width="100%" style="background-color: #fef2f2; border-left: 4px solid #ef4444; border-radius: 8px;">
                <tr>
                    <td>
                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                            <tr>
                                <td style="font-size: 13px; font-weight: bold; color: #7f1d1d; padding-bottom: 10px;">
                                    🔍 {category.upper()} BREAKDOWN: ${deep_dive['total']:,.2f}
                                </td>
                            </tr>
    '''

    if 'subcategories' in deep_dive:
        subs = deep_dive['subcategories']
        html += f'''
                            <tr>
                                <td style="font-size: 12px; color: #991b1b; padding: 3px 0;">
                                    • Restaurant sit-down: ${subs['sit_down']['total']:,.2f} ({subs['sit_down']['pct']:.0f}%) — {subs['sit_down']['count']} visits
                                </td>
                            </tr>
                            <tr>
                                <td style="font-size: 12px; color: #991b1b; padding: 3px 0;">
                                    • Delivery: ${subs['delivery']['total']:,.2f} ({subs['delivery']['pct']:.0f}%) — {subs['delivery']['count']} orders
                                </td>
                            </tr>
                            <tr>
                                <td style="font-size: 12px; color: #991b1b; padding: 3px 0;">
                                    • Quick service/coffee: ${subs['quick_service']['total']:,.2f} ({subs['quick_service']['pct']:.0f}%) — {subs['quick_service']['count']} visits
                                </td>
                            </tr>
        '''

        if subs['sit_down']['count'] > 0:
            avg_restaurant = subs['sit_down']['total'] / subs['sit_down']['count']
            html += f'''
                            <tr>
                                <td style="font-size: 12px; color: #991b1b; padding-top: 8px; font-style: italic;">
                                    💡 Avg restaurant visit = ${avg_restaurant:.2f}
                                </td>
                            </tr>
            '''

    html += '''
                        </table>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
    '''

    return html


def generate_subscription_audit_section(audit_data: Dict) -> str:
    """Generate subscription health check section"""
    html = f'''
    <tr>
        <td style="padding: 0 30px 20px 30px;">
            <table border="0" cellpadding="15" cellspacing="0" width="100%" style="background-color: #f5f3ff; border-radius: 8px; border: 1px solid #d8b4fe;">
                <tr>
                    <td>
                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                            <tr>
                                <td style="font-size: 13px; font-weight: bold; color: #581c87; padding-bottom: 10px;">
                                    💳 SUBSCRIPTION HEALTH CHECK
                                </td>
                            </tr>
    '''

    for sub in audit_data['subscriptions']:
        status_icon = "✓" if sub['status'] == 'active' else ("⚠️" if sub['status'] == 'minimal' else "❌")
        status_color = "#16a34a" if sub['status'] == 'active' else ("#f97316" if sub['status'] == 'minimal' else "#dc2626")

        html += f'''
                            <tr>
                                <td style="font-size: 12px; color: #6b21a8; padding: 5px 0;">
                                    {status_icon} <strong>{sub['merchant']}</strong>: ${sub['monthly_amt']:.2f}/mo (${sub['annual_cost']:.2f}/year)
                                </td>
                            </tr>
        '''

        if sub['status'] == 'unused':
            html += f'''
                            <tr>
                                <td style="font-size: 11px; color: {status_color}; padding-left: 20px;">
                                    └─ Not used this month — consider canceling
                                </td>
                            </tr>
            '''
        elif sub['status'] == 'minimal':
            html += f'''
                            <tr>
                                <td style="font-size: 11px; color: {status_color}; padding-left: 20px;">
                                    └─ Used {sub['usage_count']}x this month — review if worth it
                                </td>
                            </tr>
            '''

    if audit_data['potential_savings'] > 0:
        html += f'''
                            <tr>
                                <td style="font-size: 13px; font-weight: bold; color: #581c87; padding-top: 15px; border-top: 1px solid #d8b4fe;">
                                    💰 Potential savings: ${audit_data['potential_savings']:.2f}/mo (${audit_data['potential_annual_savings']:.2f}/year)
                                </td>
                            </tr>
        '''

    html += '''
                        </table>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
    '''

    return html


def generate_upcoming_charges_section(upcoming: List[Dict]) -> str:
    """Generate forward-looking alerts section"""
    if not upcoming:
        return ""

    html = '''
    <tr>
        <td style="padding: 0 30px 20px 30px;">
            <table border="0" cellpadding="12" cellspacing="0" width="100%" style="background-color: #ecfdf5; border-left: 4px solid #10b981; border-radius: 8px;">
                <tr>
                    <td>
                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                            <tr>
                                <td style="font-size: 13px; font-weight: bold; color: #064e3b; padding-bottom: 10px;">
                                    ⏭️ UPCOMING IN NEXT MONTH
                                </td>
                            </tr>
    '''

    for charge in upcoming:
        charge_type = "Annual" if charge['type'] == 'annual' else "Monthly"
        html += f'''
                            <tr>
                                <td style="font-size: 12px; color: #065f46; padding: 3px 0;">
                                    • {charge['merchant']}: ${charge['amount']:.2f} ({charge_type})
                                </td>
                            </tr>
        '''

    html += '''
                        </table>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
    '''

    return html


def generate_budget_tracking_section(category_totals: Dict[str, float], budget_config: Dict) -> str:
    """Generate budget tracking progress section"""
    if not budget_config.get('enable_budget_alerts'):
        return ""

    budgets = budget_config.get('monthly_budgets', {})
    total_budget = budget_config.get('total_monthly_budget', 0)

    # Filter categories with budgets
    tracked_categories = {cat: bud for cat, bud in budgets.items() if bud > 0}
    if not tracked_categories:
        return ""

    html = '''
    <tr>
        <td style="padding: 0 30px 20px 30px;">
            <table border="0" cellpadding="15" cellspacing="0" width="100%" style="background-color: #f0f9ff; border-radius: 8px; border: 1px solid #7dd3fc;">
                <tr>
                    <td>
                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                            <tr>
                                <td style="font-size: 13px; font-weight: bold; color: #0c4a6e; padding-bottom: 12px;">
                                    🎯 BUDGET TRACKING
                                </td>
                            </tr>
    '''

    total_spent = sum(category_totals.values())
    overall_pct = (total_spent / total_budget * 100) if total_budget > 0 else 0

    for category, budget in tracked_categories.items():
        spent = category_totals.get(category, 0)
        pct_used = (spent / budget * 100) if budget > 0 else 0

        # Color code based on usage
        if pct_used > 100:
            status = "❌ Over"
            color = "#dc2626"
        elif pct_used >= 90:
            status = "⚠️ Near"
            color = "#f59e0b"
        else:
            status = "✓"
            color = "#22c55e"

        bar_width = min(int(pct_used), 100)  # Cap at 100% width

        html += f'''
                            <tr>
                                <td style="font-size: 12px; color: #0c4a6e; padding: 8px 0;">
                                    <strong>{category}:</strong> ${spent:,.0f} / ${budget:,.0f} budget ({pct_used:.0f}% used) <span style="color: {color};">{status}</span>
                                    <div style="background: #e0f2fe; height: 8px; border-radius: 4px; margin-top: 4px; overflow: hidden;">
                                        <div style="background: {color}; height: 8px; width: {bar_width}%;"></div>
                                    </div>
                                </td>
                            </tr>
        '''

    # Overall budget
    overall_status = "✓" if overall_pct < 100 else ("⚠️" if overall_pct < 110 else "❌")
    overall_color = "#22c55e" if overall_pct < 100 else ("#f59e0b" if overall_pct < 110 else "#dc2626")

    html += f'''
                            <tr>
                                <td style="font-size: 13px; font-weight: bold; color: #0c4a6e; padding-top: 12px; border-top: 2px solid #7dd3fc;">
                                    <strong>Overall:</strong> ${total_spent:,.2f} / ${total_budget:,.2f} monthly budget ({overall_pct:.0f}%) <span style="color: {overall_color};">{overall_status}</span>
                                </td>
                            </tr>
    '''

    html += '''
                        </table>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
    '''

    return html

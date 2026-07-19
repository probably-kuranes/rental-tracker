"""
Rental Property Tracker - Streamlit Dashboard

Every section is scoped to the period chosen in the sidebar, and the active
period is stated in each section header. Management fees (a function of
income) are shown separately from operating expenses (repairs etc.)
throughout. Multi-month statements (e.g. annual statements) are excluded from
monthly aggregates to avoid double counting and are summarized separately.
"""

from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.database import Database, Owner, Property, MonthlyReport, PropertyMonth, Expense

# Page configuration
st.set_page_config(
    page_title="Rental Property Tracker",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# A statement covering more than this many days is treated as multi-month
# (annual statements) rather than a monthly statement.
MONTHLY_MAX_DAYS = 35

COLOR_INCOME = '#2ecc71'
COLOR_MGMT = '#f39c12'
COLOR_OPEX = '#e74c3c'
COLOR_NOI = '#3498db'


@st.cache_resource
def get_db():
    """Get database connection."""
    import os
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        if os.path.exists('rental_tracker.db'):
            db_url = 'sqlite:///rental_tracker.db'
        elif os.path.exists('sample_data.db'):
            db_url = 'sqlite:///sample_data.db'
        else:
            db_url = 'sqlite:///rental_tracker.db'

    db = Database(db_url)
    try:
        db.create_tables()
    except Exception:
        pass
    return db


def load_data():
    """Load all data and build one denormalized property-month dataframe."""
    db = get_db()

    with db.session() as session:
        owners = pd.DataFrame([{
            'owner_id': o.id, 'owner': o.name
        } for o in session.query(Owner).all()])

        properties = pd.DataFrame([{
            'property_id': p.id, 'owner_id': p.owner_id, 'address': p.address,
            'current_rent': p.current_rent,
        } for p in session.query(Property).all()])

        reports = pd.DataFrame([{
            'report_id': r.id, 'owner_id': r.owner_id,
            'period_start': r.period_start, 'period_end': r.period_end,
            'report_income': r.income, 'report_expenses': r.expenses,
            'report_mgmt_fees': r.mgmt_fees,
        } for r in session.query(MonthlyReport).all()])

        pm = pd.DataFrame([{
            'pm_id': pm_.id, 'property_id': pm_.property_id,
            'report_id': pm_.monthly_report_id,
            'income': pm_.total_income, 'expenses': pm_.total_expenses,
            'mgmt_fees': pm_.mgmt_fees, 'repairs': pm_.repairs,
            'noi': pm_.noi,
        } for pm_ in session.query(PropertyMonth).all()])

        expenses = pd.DataFrame([{
            'pm_id': e.property_month_id, 'date': e.date, 'vendor': e.vendor,
            'description': e.description, 'amount': e.amount,
            'category': e.category,
        } for e in session.query(Expense).all()])

    if pm.empty or properties.empty:
        return None

    df = (pm
          .merge(reports, on='report_id')
          .merge(properties, on='property_id', suffixes=('', '_prop'))
          .merge(owners, on='owner_id'))
    df['period_start'] = pd.to_datetime(df['period_start'])
    df['period_end'] = pd.to_datetime(df['period_end'])
    df['period_days'] = (df['period_end'] - df['period_start']).dt.days + 1
    df['is_monthly'] = df['period_days'] <= MONTHLY_MAX_DAYS
    df['month'] = df['period_end'].dt.to_period('M').dt.to_timestamp()
    # Operating expenses exclude management fees (which scale with income)
    df['opex'] = (df['expenses'] - df['mgmt_fees']).clip(lower=0)

    reports['period_start'] = pd.to_datetime(reports['period_start'])
    reports['period_end'] = pd.to_datetime(reports['period_end'])
    reports['period_days'] = (reports['period_end'] - reports['period_start']).dt.days + 1
    reports = reports.merge(owners, on='owner_id')

    return {'pm': df, 'reports': reports, 'expenses': expenses,
            'owners': owners, 'properties': properties}


def pick_period():
    """Sidebar period selector. Returns (start, end, label)."""
    today = date.today()
    presets = {
        f'{today.year} year to date': (date(today.year, 1, 1), today),
        'Last 3 months': (today - timedelta(days=92), today),
        'Monthly data era (Dec 2025 on)': (date(2025, 12, 1), today),
        'Calendar 2025': (date(2025, 1, 1), date(2025, 12, 31)),
        'All time': (date(2000, 1, 1), today),
        'Custom range': None,
    }
    choice = st.sidebar.selectbox("Period", list(presets.keys()), index=0)
    if choice == 'Custom range':
        start = st.sidebar.date_input("From", date(today.year, 1, 1))
        end = st.sidebar.date_input("To", today)
    else:
        start, end = presets[choice]
    label = f"{start:%-d %b %Y} – {end:%-d %b %Y}"
    return pd.Timestamp(start), pd.Timestamp(end), label


def money(x):
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def main():
    st.title("🏠 Rental Property Tracker Dashboard")

    if st.sidebar.button("🔄 Refresh Data"):
        st.cache_resource.clear()
        st.rerun()

    data = load_data()
    if data is None:
        st.warning("📭 No data found. Run the rental tracker to import owner statements.")
        return

    pm_all = data['pm']

    # ---- Sidebar filters ---------------------------------------------------
    st.sidebar.header("Filters")
    start, end, period_label = pick_period()

    owner_options = ['All'] + sorted(pm_all['owner'].unique().tolist())
    selected_owner = st.sidebar.selectbox("Owner", owner_options)

    property_options = ['All'] + sorted(pm_all['address'].unique().tolist())
    selected_property = st.sidebar.selectbox("Property", property_options)

    # Rows whose statement period ends inside the selected window
    in_period = pm_all[(pm_all['period_end'] >= start) & (pm_all['period_end'] <= end)]
    if selected_owner != 'All':
        in_period = in_period[in_period['owner'] == selected_owner]
    if selected_property != 'All':
        in_period = in_period[in_period['address'] == selected_property]

    # Monthly rows drive all aggregates; multi-month statements are reported
    # separately so overlapping periods are never double counted.
    monthly = in_period[in_period['is_monthly']]
    multi = in_period[~in_period['is_monthly']]

    n_months = monthly['month'].nunique()
    n_props = monthly['address'].nunique()

    # ---- Portfolio overview ------------------------------------------------
    st.header(f"📊 Portfolio Overview — {period_label}")

    if monthly.empty:
        st.info("No monthly statement data in this period.")
    else:
        income = monthly['income'].sum()
        mgmt = monthly['mgmt_fees'].sum()
        opex = monthly['opex'].sum()
        noi = monthly['noi'].sum()

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Income", money(income))
        c2.metric("Mgmt Fees", money(mgmt))
        c3.metric("Operating Expenses", money(opex))
        c4.metric("Net Operating Income", money(noi))
        c5.metric("Avg NOI / month", money(noi / n_months) if n_months else "–")
        st.caption(
            f"Based on {len(monthly)} property-months across {n_props} propert"
            f"{'ies' if n_props != 1 else 'y'} and {n_months} calendar month"
            f"{'s' if n_months != 1 else ''} of statements. "
            f"Coverage varies by property — see Property Details."
        )

    if not multi.empty:
        st.markdown("**Multi-month statements in this period** "
                    "(kept out of the monthly figures above to avoid double counting):")
        for _, r in multi.iterrows():
            st.markdown(
                f"- {r['address']} ({r['owner']}), "
                f"{r['period_start']:%b %Y} – {r['period_end']:%b %Y}: "
                f"income {money(r['income'])}, NOI {money(r['noi'])}"
            )
    # Multi-month statements with no property split (portfolio level only)
    rep = data['reports']
    rep_multi = rep[(rep['period_days'] > MONTHLY_MAX_DAYS)
                    & (rep['period_end'] >= start) & (rep['period_end'] <= end)]
    if selected_owner != 'All':
        rep_multi = rep_multi[rep_multi['owner'] == selected_owner]
    rep_multi = rep_multi[~rep_multi['report_id'].isin(multi['report_id'] if not multi.empty else [])]
    known_ids = set(pm_all['report_id'])
    rep_only = rep_multi[~rep_multi['report_id'].isin(known_ids)]
    if not rep_only.empty:
        st.markdown("**Annual/multi-month statements (portfolio totals only):**")
        for _, r in rep_only.iterrows():
            st.markdown(
                f"- {r['owner']}, {r['period_start']:%b %Y} – {r['period_end']:%b %Y}: "
                f"income {money(r['report_income'])}, "
                f"expenses {money(r['report_expenses'])}"
            )

    st.markdown("---")

    # ---- Property performance ---------------------------------------------
    st.header(f"🏘️ Property Performance — {period_label}")

    if monthly.empty:
        st.info("No monthly data in this period.")
    else:
        agg = monthly.groupby('address').agg(
            income=('income', 'sum'),
            mgmt=('mgmt_fees', 'sum'),
            opex=('opex', 'sum'),
            noi=('noi', 'sum'),
            months=('month', 'nunique'),
        ).reset_index().sort_values('income', ascending=False)

        fig = go.Figure()
        fig.add_trace(go.Bar(
            name='Income', x=agg['address'], y=agg['income'],
            marker_color=COLOR_INCOME))
        fig.add_trace(go.Bar(
            name='Mgmt fees', x=agg['address'], y=-agg['mgmt'],
            marker_color=COLOR_MGMT))
        fig.add_trace(go.Bar(
            name='Operating expenses', x=agg['address'], y=-agg['opex'],
            marker_color=COLOR_OPEX))
        fig.add_trace(go.Scatter(
            name='NOI', x=agg['address'], y=agg['noi'],
            mode='markers', marker=dict(color=COLOR_NOI, size=14, symbol='diamond')))
        fig.update_layout(
            barmode='relative',
            title=f'Income up, costs down; ◆ = NOI ({period_label})',
            yaxis_title='Amount ($)', height=450,
            legend=dict(orientation='h', y=1.12),
        )
        fig.add_hline(y=0, line_width=1, line_color='#888')
        st.plotly_chart(fig, width='stretch')

        # ---- Property details (one row per property) ----------------------
        st.subheader(f"Property Details — {period_label}")
        det = agg.copy()
        det['noi_margin'] = (det['noi'] / det['income']).where(det['income'] > 0)
        det['avg_noi_month'] = det['noi'] / det['months']
        show = pd.DataFrame({
            'Property': det['address'],
            'Months of data': det['months'],
            'Income': det['income'].map(money),
            'Mgmt Fees': det['mgmt'].map(money),
            'Op. Expenses': det['opex'].map(money),
            'NOI': det['noi'].map(money),
            'NOI / month': det['avg_noi_month'].map(money),
            'NOI Margin': det['noi_margin'].map(
                lambda v: f"{v*100:.0f}%" if pd.notna(v) else "–"),
        })
        st.dataframe(show, width='stretch', hide_index=True)
        if det['months'].nunique() > 1:
            st.caption("⚠️ Months of data differ between properties — compare "
                       "NOI / month, not totals.")

    st.markdown("---")

    # ---- Trends ------------------------------------------------------------
    st.header(f"📈 Monthly Trends — {period_label}")

    if monthly.empty or monthly['month'].nunique() < 2:
        st.info("Trends appear once the period contains at least two months of monthly statements.")
    else:
        month_index = pd.period_range(
            monthly['month'].min(), monthly['month'].max(), freq='M'
        ).to_timestamp()

        by_month = (monthly.groupby('month')
                    .agg(income=('income', 'sum'), mgmt=('mgmt_fees', 'sum'),
                         opex=('opex', 'sum'), noi=('noi', 'sum'))
                    .reindex(month_index))

        fig_t = go.Figure()
        for col, label, color in [('income', 'Income', COLOR_INCOME),
                                  ('mgmt', 'Mgmt fees', COLOR_MGMT),
                                  ('opex', 'Operating expenses', COLOR_OPEX),
                                  ('noi', 'NOI', COLOR_NOI)]:
            fig_t.add_trace(go.Scatter(
                x=by_month.index, y=by_month[col], name=label,
                mode='lines+markers', line=dict(color=color),
                connectgaps=False))
        fig_t.update_layout(
            title='Portfolio by month (gaps = no statement received)',
            yaxis_title='Amount ($)', height=420,
            legend=dict(orientation='h', y=1.12))
        st.plotly_chart(fig_t, width='stretch')

        prop_noi = (monthly.groupby(['month', 'address'])['noi'].sum()
                    .unstack().reindex(month_index))
        fig_p = go.Figure()
        for addr in prop_noi.columns:
            fig_p.add_trace(go.Scatter(
                x=prop_noi.index, y=prop_noi[addr], name=addr,
                mode='lines+markers', connectgaps=False))
        fig_p.update_layout(
            title='NOI by property (gaps = no statement for that property that month)',
            yaxis_title='NOI ($)', height=420)
        st.plotly_chart(fig_p, width='stretch')

    st.markdown("---")

    # ---- Expense breakdown -------------------------------------------------
    st.header(f"💰 Expense Breakdown — {period_label}")

    exp = data['expenses']
    if exp.empty or in_period.empty:
        st.info("No expense line items in this period.")
    else:
        exp_period = exp[exp['pm_id'].isin(in_period['pm_id'])].copy()
        # Management fees are shown in their own metrics; the breakdown is
        # about operating expenses (things that went wrong / upkeep).
        exp_op = exp_period[exp_period['category'] != 'Management Fee']

        if exp_op.empty:
            st.info("No operating-expense line items in this period.")
        else:
            col1, col2 = st.columns(2)

            with col1:
                by_cat = exp_op.groupby('category')['amount'].sum().reset_index()
                fig_pie = px.pie(by_cat, values='amount', names='category',
                                 title=f'Operating expenses by category ({period_label})',
                                 hole=0.4)
                st.plotly_chart(fig_pie, width='stretch')

            with col2:
                st.subheader("Top expenses")
                top = exp_op.nlargest(12, 'amount')[
                    ['date', 'amount', 'category', 'vendor', 'description']]
                st.dataframe(
                    top,
                    width='stretch', hide_index=True,
                    column_config={
                        'date': st.column_config.DateColumn('Date'),
                        'amount': st.column_config.NumberColumn(
                            'Amount', format='$%.2f'),
                        'category': 'Category',
                        'vendor': 'Vendor',
                        'description': st.column_config.TextColumn(
                            'Description', width='medium'),
                    })

    st.markdown("---")

    # ---- Alerts ------------------------------------------------------------
    st.header(f"🚨 Alerts — {period_label}")

    if monthly.empty:
        st.info("No monthly data in this period.")
    else:
        alerts = []
        agg = monthly.groupby('address').agg(
            income=('income', 'sum'), opex=('opex', 'sum'),
            repairs=('repairs', 'sum'), noi=('noi', 'sum'),
            months=('month', 'nunique')).reset_index()

        for _, row in agg.iterrows():
            if row['income'] > 0:
                opex_ratio = row['opex'] / row['income']
                noi_margin = row['noi'] / row['income']
                if opex_ratio > 0.3:
                    alerts.append({'Alert': '⚠️ High operating-expense ratio',
                                   'Property': row['address'],
                                   'Detail': f"{opex_ratio*100:.0f}% of income over {row['months']} month(s)"})
                if noi_margin < 0.5:
                    alerts.append({'Alert': '⚠️ Low NOI margin',
                                   'Property': row['address'],
                                   'Detail': f"{noi_margin*100:.0f}% over {row['months']} month(s)"})
            else:
                alerts.append({'Alert': '🏚️ No income',
                               'Property': row['address'],
                               'Detail': f"$0 income, {money(row['opex'])} expenses over {row['months']} month(s)"})
            if row['repairs'] > 500 * row['months']:
                alerts.append({'Alert': '🔧 High repair costs',
                               'Property': row['address'],
                               'Detail': f"{money(row['repairs'])} over {row['months']} month(s)"})

        if alerts:
            st.dataframe(pd.DataFrame(alerts), width='stretch', hide_index=True)
        else:
            st.success(f"✅ No alerts for {period_label}.")

    st.markdown("---")

    # ---- Export ------------------------------------------------------------
    st.header("⬇️ Export")

    col1, col2 = st.columns(2)
    with col1:
        if not in_period.empty:
            out = in_period[['address', 'owner', 'period_start', 'period_end',
                             'income', 'mgmt_fees', 'opex', 'expenses',
                             'repairs', 'noi']].copy()
            out['period_start'] = out['period_start'].dt.date
            out['period_end'] = out['period_end'].dt.date
            st.download_button(
                "Property months (CSV)",
                out.to_csv(index=False).encode('utf-8'),
                file_name=f"property_months_{datetime.now():%Y%m%d}.csv",
                mime="text/csv")
    with col2:
        if not exp.empty and not in_period.empty:
            out_e = exp[exp['pm_id'].isin(in_period['pm_id'])][
                ['date', 'vendor', 'description', 'amount', 'category']]
            st.download_button(
                "Expense line items (CSV)",
                out_e.to_csv(index=False).encode('utf-8'),
                file_name=f"expenses_{datetime.now():%Y%m%d}.csv",
                mime="text/csv")

    st.markdown("---")
    st.caption(f"Period: {period_label} · Last updated: {datetime.now():%Y-%m-%d %H:%M:%S}")


if __name__ == "__main__":
    main()

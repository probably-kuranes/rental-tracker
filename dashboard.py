"""
Rental Property Tracker - Streamlit Dashboard

A web-based dashboard for viewing rental property performance,
expenses, and financial metrics.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from sqlalchemy import func
from src.database import Database, Owner, Property, MonthlyReport, PropertyMonth, Expense

# Page configuration
st.set_page_config(
    page_title="Rental Property Tracker",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
    <style>
    .metric-card {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        border-left: 5px solid #1f77b4;
    }
    .stMetric {
        background-color: #ffffff;
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    </style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_db():
    """Get database connection."""
    import os
    # Determine which database to use
    if os.path.exists('rental_tracker.db'):
        db_url = 'sqlite:///rental_tracker.db'
    elif os.path.exists('sample_data.db'):
        db_url = 'sqlite:///sample_data.db'
    else:
        # Fallback - create empty database
        db_url = 'sqlite:///rental_tracker.db'

    db = Database(db_url)
    # Ensure tables exist
    try:
        db.create_tables()
    except:
        pass
    return db


def load_data():
    """Load all data from the database."""
    db = get_db()

    with db.session() as session:
        # Get all data
        owners = session.query(Owner).all()
        properties = session.query(Property).all()
        monthly_reports = session.query(MonthlyReport).all()
        property_months = session.query(PropertyMonth).all()
        expenses = session.query(Expense).all()

        # Convert to dictionaries for easier handling
        owners_data = [{
            'id': o.id,
            'name': o.name,
            'created_at': o.created_at
        } for o in owners]

        properties_data = [{
            'id': p.id,
            'owner_id': p.owner_id,
            'address': p.address,
            'current_rent': p.current_rent,
            'security_deposit': p.security_deposit,
            'is_active': p.is_active
        } for p in properties]

        monthly_reports_data = [{
            'id': mr.id,
            'owner_id': mr.owner_id,
            'period_start': mr.period_start,
            'period_end': mr.period_end,
            'income': mr.income,
            'expenses': mr.expenses,
            'mgmt_fees': mr.mgmt_fees,
            'ending_balance': mr.ending_balance,
            'due_to_owner': mr.due_to_owner
        } for mr in monthly_reports]

        property_months_data = [{
            'id': pm.id,
            'property_id': pm.property_id,
            'monthly_report_id': pm.monthly_report_id,
            'total_income': pm.total_income,
            'total_expenses': pm.total_expenses,
            'mgmt_fees': pm.mgmt_fees,
            'repairs': pm.repairs,
            'noi': pm.noi,
            'noi_margin': pm.noi_margin,
            'expense_ratio': pm.expense_ratio
        } for pm in property_months]

        expenses_data = [{
            'id': e.id,
            'property_month_id': e.property_month_id,
            'date': e.date,
            'vendor': e.vendor,
            'description': e.description,
            'amount': e.amount,
            'category': e.category
        } for e in expenses]

        return {
            'owners': pd.DataFrame(owners_data) if owners_data else pd.DataFrame(),
            'properties': pd.DataFrame(properties_data) if properties_data else pd.DataFrame(),
            'monthly_reports': pd.DataFrame(monthly_reports_data) if monthly_reports_data else pd.DataFrame(),
            'property_months': pd.DataFrame(property_months_data) if property_months_data else pd.DataFrame(),
            'expenses': pd.DataFrame(expenses_data) if expenses_data else pd.DataFrame()
        }


def main():
    """Main dashboard function."""

    # Title
    st.title("🏠 Rental Property Tracker Dashboard")

    # Add refresh button in sidebar
    if st.sidebar.button("🔄 Refresh Data"):
        st.cache_resource.clear()
        st.rerun()

    st.markdown("---")

    # Load data
    data = load_data()

    # Check if we have data
    if data['properties'].empty:
        st.warning("📭 No data found. Run the rental tracker to import owner statements.")
        st.info("Run: `python3 scripts/run_agent.py --verbose` to process emails")
        return

    # Sidebar filters
    st.sidebar.header("Filters")

    # Owner filter
    if not data['owners'].empty:
        owner_options = ['All'] + data['owners']['name'].tolist()
        selected_owner = st.sidebar.selectbox("Owner", owner_options)
    else:
        selected_owner = 'All'

    # Property filter
    if not data['properties'].empty:
        property_options = ['All'] + data['properties']['address'].tolist()
        selected_property = st.sidebar.selectbox("Property", property_options)
    else:
        selected_property = 'All'

    # Filter data based on selections
    filtered_properties = data['properties'].copy()
    if selected_owner != 'All':
        owner_id = data['owners'][data['owners']['name'] == selected_owner]['id'].iloc[0]
        filtered_properties = filtered_properties[filtered_properties['owner_id'] == owner_id]

    if selected_property != 'All':
        filtered_properties = filtered_properties[filtered_properties['address'] == selected_property]

    # Get filtered property IDs
    property_ids = filtered_properties['id'].tolist()

    # Filter property months
    if not data['property_months'].empty and property_ids:
        filtered_pm = data['property_months'][data['property_months']['property_id'].isin(property_ids)]
    else:
        filtered_pm = data['property_months'].copy()

    # Portfolio Overview
    st.header("📊 Portfolio Overview")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        total_properties = len(filtered_properties)
        st.metric("Total Properties", total_properties)

    with col2:
        if not filtered_pm.empty:
            total_income = filtered_pm['total_income'].sum()
            st.metric("Total Income", f"${total_income:,.2f}")
        else:
            st.metric("Total Income", "$0.00")

    with col3:
        if not filtered_pm.empty:
            total_expenses = filtered_pm['total_expenses'].sum()
            st.metric("Total Expenses", f"${total_expenses:,.2f}")
        else:
            st.metric("Total Expenses", "$0.00")

    with col4:
        if not filtered_pm.empty:
            total_noi = filtered_pm['noi'].sum()
            st.metric("Net Operating Income", f"${total_noi:,.2f}")
        else:
            st.metric("Net Operating Income", "$0.00")

    st.markdown("---")

    # Property Performance
    st.header("🏘️ Property Performance")

    if not filtered_pm.empty:
        # Merge with property data to get addresses
        pm_with_address = filtered_pm.merge(
            filtered_properties[['id', 'address']],
            left_on='property_id',
            right_on='id',
            suffixes=('', '_prop')
        )

        # Create performance chart
        fig_performance = go.Figure()

        fig_performance.add_trace(go.Bar(
            name='Income',
            x=pm_with_address['address'],
            y=pm_with_address['total_income'],
            marker_color='#2ecc71'
        ))

        fig_performance.add_trace(go.Bar(
            name='Expenses',
            x=pm_with_address['address'],
            y=pm_with_address['total_expenses'],
            marker_color='#e74c3c'
        ))

        fig_performance.add_trace(go.Bar(
            name='NOI',
            x=pm_with_address['address'],
            y=pm_with_address['noi'],
            marker_color='#3498db'
        ))

        fig_performance.update_layout(
            barmode='group',
            title='Income, Expenses, and NOI by Property',
            xaxis_title='Property',
            yaxis_title='Amount ($)',
            height=400
        )

        st.plotly_chart(fig_performance, use_container_width=True)

        # Property details table
        st.subheader("Property Details")

        display_df = pm_with_address[['address', 'total_income', 'total_expenses', 'noi', 'noi_margin', 'expense_ratio']].copy()
        display_df.columns = ['Property', 'Income', 'Expenses', 'NOI', 'NOI Margin %', 'Expense Ratio %']
        display_df['NOI Margin %'] = (display_df['NOI Margin %'] * 100).round(1)
        display_df['Expense Ratio %'] = (display_df['Expense Ratio %'] * 100).round(1)
        display_df['Income'] = display_df['Income'].apply(lambda x: f"${x:,.2f}")
        display_df['Expenses'] = display_df['Expenses'].apply(lambda x: f"${x:,.2f}")
        display_df['NOI'] = display_df['NOI'].apply(lambda x: f"${x:,.2f}")

        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("No property performance data available.")

    st.markdown("---")

    # Expense Breakdown
    st.header("💰 Expense Breakdown")

    if not data['expenses'].empty and not filtered_pm.empty:
        # Get expenses for filtered properties
        filtered_expenses = data['expenses'][
            data['expenses']['property_month_id'].isin(filtered_pm['id'])
        ]

        if not filtered_expenses.empty:
            col1, col2 = st.columns(2)

            with col1:
                # Expense by category pie chart
                expense_by_category = filtered_expenses.groupby('category')['amount'].sum().reset_index()

                fig_pie = px.pie(
                    expense_by_category,
                    values='amount',
                    names='category',
                    title='Expenses by Category',
                    hole=0.4
                )
                st.plotly_chart(fig_pie, use_container_width=True)

            with col2:
                # Top expenses
                st.subheader("Top Expenses")
                top_expenses = filtered_expenses.nlargest(10, 'amount')[['date', 'vendor', 'description', 'amount', 'category']]
                top_expenses['amount'] = top_expenses['amount'].apply(lambda x: f"${x:,.2f}")
                st.dataframe(top_expenses, use_container_width=True, hide_index=True)
        else:
            st.info("No expense data available for selected filters.")
    else:
        st.info("No expense data available.")

    st.markdown("---")

    # Alerts
    st.header("🚨 Alerts")

    if not filtered_pm.empty:
        alerts = []

        # High expense ratio alert
        high_expense = filtered_pm[filtered_pm['expense_ratio'] > 0.3]
        if not high_expense.empty:
            for _, row in high_expense.iterrows():
                prop = filtered_properties[filtered_properties['id'] == row['property_id']]['address'].iloc[0]
                alerts.append({
                    'type': '⚠️ High Expense Ratio',
                    'property': prop,
                    'message': f"Expense ratio: {row['expense_ratio']*100:.1f}%"
                })

        # Low NOI margin alert
        low_noi = filtered_pm[filtered_pm['noi_margin'] < 0.2]
        if not low_noi.empty:
            for _, row in low_noi.iterrows():
                prop = filtered_properties[filtered_properties['id'] == row['property_id']]['address'].iloc[0]
                alerts.append({
                    'type': '⚠️ Low NOI Margin',
                    'property': prop,
                    'message': f"NOI margin: {row['noi_margin']*100:.1f}%"
                })

        # High repairs alert
        high_repairs = filtered_pm[filtered_pm['repairs'] > 500]
        if not high_repairs.empty:
            for _, row in high_repairs.iterrows():
                prop = filtered_properties[filtered_properties['id'] == row['property_id']]['address'].iloc[0]
                alerts.append({
                    'type': '🔧 High Repair Costs',
                    'property': prop,
                    'message': f"Repairs: ${row['repairs']:,.2f}"
                })

        if alerts:
            alerts_df = pd.DataFrame(alerts)
            st.dataframe(alerts_df, use_container_width=True, hide_index=True)
        else:
            st.success("✅ No alerts - all properties performing well!")

    # Footer
    st.markdown("---")
    st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()

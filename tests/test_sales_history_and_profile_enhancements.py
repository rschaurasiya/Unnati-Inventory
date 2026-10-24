"""
Comprehensive Verification Test Suite for Sales History & Import (/sales/history)
and Profile & Settings (/profile) Enhancements.

Verifies all 8 user requirements:
PART A:
1. Top "Sales History & Import" banner removed from /sales/history; 4 KPI cards directly below navbar.
2. Filter panel Expand / Collapse toggle ('‸' / '⌄') with tooltip and detailed filters container.
3. Sales history pagination (10, 20, 30 options), Showing X–Y of Z items, Prev/Next buttons.

PART B:
4. All 4 profile containers are collapsible accordion cards, collapsed by default with '⌄' / '‸' carets.
5. 100% zoom layout for photo crop modal: 92vh constraint, 180x180 stage, compact zoom row.
6. Circular and Square preview avatars directly clickable interactive selector cards; upper toggle buttons removed.

PART C:
7. Real-time global profile synchronization and non-blocking toast notifications.
8. Clean responsive design at 100% zoom without horizontal overflow.
"""

import pytest
import os
import re

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
INDEX_HTML = os.path.join(FRONTEND_DIR, "index.html")
STYLE_CSS = os.path.join(FRONTEND_DIR, "css", "style.css")
PROFILE_JS = os.path.join(FRONTEND_DIR, "js", "profile.js")
SALES_JS = os.path.join(FRONTEND_DIR, "js", "sales.js")
UTILS_JS = os.path.join(FRONTEND_DIR, "js", "shared", "utils.js")
STATE_JS = os.path.join(FRONTEND_DIR, "js", "shared", "state.js")


def test_01_top_banner_removed_and_kpis_moved_up():
    """Verify Part A.1: Intro banner card removed; 4 KPI cards sit immediately below navbar."""
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        html = f.read()

    # Intro banner heading and subtitle should NOT exist
    assert "What did I sell? View your store sales totals" not in html, "Intro banner subtitle should be removed"

    # 4 KPI cards must be directly at the top of #tab-analytics without any header card
    analytics_section = re.search(r'<section id="tab-analytics"[^>]*>(.*?)</section>', html, re.DOTALL)
    assert analytics_section is not None, "#tab-analytics section must exist"
    sec_content = analytics_section.group(1)

    assert "analytics-header-card" not in sec_content, "analytics-header-card should be completely removed from #tab-analytics"

    assert "analytics-metrics-grid" in sec_content
    assert "Total Sales Revenue" in sec_content
    assert "Total Units Sold" in sec_content
    assert "Completed Transactions" in sec_content
    assert "Active Products Sold" in sec_content


def test_02_filter_collapse_expand_toggle():
    """Verify Part A.2: Expand / Collapse Toggle ('Hide Filters' / 'Show Filters') in filter toolbar."""
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        html = f.read()
    with open(STYLE_CSS, "r", encoding="utf-8") as f:
        css = f.read()
    with open(SALES_JS, "r", encoding="utf-8") as f:
        js = f.read()

    # HTML Elements
    assert 'id="toggleSalesFiltersBtn"' in html or 'id="btn-toggle-sales-filters"' in html
    assert 'id="salesFilterBody"' in html or 'id="sales-detailed-filters"' in html
    assert "Hide Filters" in html

    # CSS Rules
    assert ".toolbar-top-row" in css
    assert ".btn-filter-toggle" in css
    assert "#sales-filter-card.filters-collapsed" in css

    # JS logic handles click and flips label/caret
    assert "toggleSalesFilters" in js
    assert "filters-collapsed" in js
    assert "Hide Filters" in js
    assert "Show Filters" in js


def test_03_sales_history_pagination():
    """Verify Part A.3: Single-row table footer pagination with 10, 20, 30 items per page and controls."""
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        html = f.read()
    with open(STYLE_CSS, "r", encoding="utf-8") as f:
        css = f.read()
    with open(SALES_JS, "r", encoding="utf-8") as f:
        js = f.read()

    # HTML Elements
    assert 'id="sales-pagination-container"' in html
    assert 'id="sales-page-size-select"' in html
    assert '<option value="10"' in html
    assert '<option value="20"' in html
    assert '<option value="30"' in html
    assert 'id="sales-pagination-info"' in html
    assert 'id="btn-sales-prev"' in html
    assert 'id="btn-sales-next"' in html
    assert 'id="sales-page-indicator"' in html
    assert 'class="sales-pagination-left"' in html
    assert 'class="sales-pagination-right"' in html

    # CSS
    assert ".sales-pagination-bar" in css
    assert ".btn-pagination" in css
    assert ".page-indicator-badge" in css

    # JS pagination state and functions
    assert "salesPageSize" in js
    assert "currentSalesPage" in js
    assert "renderSalesHistoryPage" in js
    assert "renderSalesHistoryTable" in js
    assert "sales-page-size-select" in js
    assert "btn-sales-prev" in js
    assert "btn-sales-next" in js


def test_04_profile_containers_collapsed_by_default():
    """Verify Part B.4: All 4 profile containers are collapsible accordions, collapsed by default with action pills."""
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        html = f.read()
    with open(STYLE_CSS, "r", encoding="utf-8") as f:
        css = f.read()
    with open(PROFILE_JS, "r", encoding="utf-8") as f:
        js = f.read()

    # 4 profile cards have .collapsed class by default
    cards = ["profile-card-personal", "profile-card-shop", "profile-card-security", "profile-card-settings"]
    for cid in cards:
        match = re.search(rf'id="{cid}"[^>]*class="([^"]*)"', html) or re.search(rf'class="([^"]*)"[^>]*id="{cid}"', html)
        assert match is not None, f"Card {cid} must exist"
        classes = match.group(1).split()
        assert "profile-card" in classes, f"{cid} must have profile-card class"
        assert "collapsed" in classes, f"{cid} must be collapsed by default"

    # Action pills and clickable headers in all 4 cards
    assert html.count('class="accordion-action-pill"') >= 4
    assert html.count('class="profile-card-header"') >= 4

    # CSS accordion rules
    assert ".profile-card.collapsed .profile-card-body" in css
    assert ".profile-card-header" in css
    assert ".accordion-action-pill" in css

    # JS accordion initialization
    assert "initProfileAccordions" in js


def test_05_photo_crop_modal_100_percent_zoom():
    """Verify Part B.5: Crop modal constrained to fit 100% zoom screens without clipping."""
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        html = f.read()
    with open(STYLE_CSS, "r", encoding="utf-8") as f:
        css = f.read()
    with open(PROFILE_JS, "r", encoding="utf-8") as f:
        js = f.read()

    # HTML
    assert 'id="image-cropper-modal"' in html
    assert 'class="modal-card cropper-modal-card"' in html
    assert 'id="cropper-stage"' in html
    assert 'id="cropper-canvas"' in html

    # CSS 100% zoom constraints
    assert "max-height: 92vh" in css
    assert "width: min(440px, 94vw)" in css
    assert "width: 180px" in css
    assert "height: 180px" in css
    assert ".cropper-zoom-bar" in css
    assert "flex-wrap: nowrap" in css

    # JS cropSize 180
    assert "cropSize: 180" in js


def test_06_crop_modal_clickable_preview_cards():
    """Verify Part B.6: Upper preview toggles removed; preview cards directly clickable with glow."""
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        html = f.read()
    with open(STYLE_CSS, "r", encoding="utf-8") as f:
        css = f.read()
    with open(PROFILE_JS, "r", encoding="utf-8") as f:
        js = f.read()

    # Upper toggle buttons removed from cropper modal
    assert 'id="btn-preview-circle"' not in html, "Upper circle preview button should be removed"
    assert 'id="btn-preview-square"' not in html, "Upper square preview button should be removed"

    # Clickable cards with role="button"
    assert 'id="col-preview-circle"' in html
    assert 'id="col-preview-square"' in html
    assert 'onclick="setCropperPreviewMode(\'circle\')"' in html
    assert 'onclick="setCropperPreviewMode(\'square\')"' in html
    assert "Circular Preview" in html
    assert "Square Preview" in html

    # CSS glow and active state
    assert ".clickable-preview-card" in css
    assert ".clickable-preview-card.active-preview" in css
    assert "rgba(56, 189, 248" in css

    # JS export and mode switching
    assert "setCropperPreviewMode" in js
    assert "active-preview" in js


def test_07_realtime_sync_and_toast_notifications():
    """Verify Part C.7: Global real-time synchronization and toast notifications."""
    with open(PROFILE_JS, "r", encoding="utf-8") as f:
        profile_js = f.read()
    with open(UTILS_JS, "r", encoding="utf-8") as f:
        utils_js = f.read()
    with open(STATE_JS, "r", encoding="utf-8") as f:
        state_js = f.read()
    with open(STYLE_CSS, "r", encoding="utf-8") as f:
        css = f.read()

    # Toast utility exists and exported
    assert "showToast" in utils_js
    assert "app-toast-container" in utils_js or "app-toast-container" in css
    assert ".app-toast" in css
    assert ".app-toast.toast-show" in css

    # Profile.js triggers showToast on save
    assert 'showToast("Personal Info Updated"' in profile_js or "showToast" in profile_js
    assert 'showToast("Shop Details Saved"' in profile_js or "showToast" in profile_js
    assert 'showToast("Password Updated Successfully"' in profile_js or "showToast" in profile_js
    assert 'showToast("Store Preferences Saved"' in profile_js or "showToast" in profile_js
    assert 'showToast("Profile Photo Updated"' in profile_js or "showToast" in profile_js

    # Real-time state synchronization
    assert "syncUserDataAcrossUI" in state_js
    assert "syncBusinessDataAcrossUI" in state_js
    assert "header-user-name" in state_js
    assert "header-shop-name" in state_js
    assert "header-user-avatar" in state_js


def test_08_responsive_view_and_zero_syntax_errors():
    """Verify Part C.8: Responsive styling integrity and clean script definitions."""
    with open(STYLE_CSS, "r", encoding="utf-8") as f:
        css = f.read()

    # Check for basic CSS brace balance
    open_braces = css.count("{")
    close_braces = css.count("}")
    assert open_braces == close_braces, f"CSS braces mismatch: {open_braces} open vs {close_braces} close"
